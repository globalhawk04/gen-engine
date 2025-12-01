import json
import re
import os
import uuid
import math

# --- USD LIBRARIES ---
try:
    from pxr import Usd, UsdGeom, UsdPhysics, UsdShade, Sdf, Gf, Vt
    HAS_USD = True
except ImportError:
    HAS_USD = False
    print("⚠️  WARNING: 'pxr' library not found. Run with ./python.sh")

# --- DATA HELPERS ---
def extract_float(val):
    if not val: return 0.0
    try: 
        match = re.search(r"[\d\.]+", str(val))
        return float(match.group()) if match else 0.0
    except: return 0.0

def parse_weight_to_kg(val):
    if not val: return 0.0
    val_str = str(val).lower().replace(" ", "")
    num = extract_float(val_str)
    if num == 0: return 0.0
    if "kg" in val_str: return num
    if "oz" in val_str: return num * 0.0283495
    if "lb" in val_str: return num * 0.453592
    return num / 1000.0

def determine_size_class(part):
    cat = part.get('category')
    name = part.get('model_name', '').lower()
    specs = part.get('specs') or {}
    
    if cat == 'Frame_Kit':
        if "usb" in name or "text" in name: return "INVALID" 
        if "7 inch" in name or "chimera" in name: return "7_INCH"
        if "5 inch" in name or "nazgul" in name: return "5_INCH"
        if "agri" in name or "vtol" in name or "tarot" in name: return "HEAVY_LIFT"
        wb = extract_float(specs.get('wheelbase_mm'))
        if wb > 450: return "HEAVY_LIFT"
        if wb > 280: return "7_INCH"
        return "5_INCH"
    
    if cat == 'Motors':
        stator = str(specs.get('stator_size', ''))
        kv = extract_float(specs.get('kv_rating'))
        if "4006" in stator or "5008" in stator: return "HEAVY_LIFT"
        if kv > 0 and kv < 500: return "HEAVY_LIFT" 
        return "5_INCH" 

    if cat == 'Propellers':
        d = extract_float(specs.get('diameter_inches') or specs.get('diameter_inch'))
        if d == 0:
            mm = extract_float(specs.get('diameter_mm'))
            if mm > 0: d = mm / 25.4
        if d >= 12: return "HEAVY_LIFT"
        return "5_INCH"

    if cat == "Battery":
        mah = extract_float(specs.get('capacity_mah'))
        if mah > 8000: return "HEAVY_LIFT"
        return "5_INCH"

    return "UNIVERSAL"

def simple_compatibility_match(frame, candidates):
    frame_specs = frame.get('specs', {})
    selected_motor = candidates['motors'][0] if candidates['motors'] else None
    
    selected_prop = None
    max_prop = float(frame_specs.get('max_prop_size_inch', 0) or 0)
    for p in candidates['props']:
        p_dia = float(p.get('specs', {}).get('diameter_inches', 0) or 0)
        if 0 < p_dia <= max_prop:
            selected_prop = p; break
    if not selected_prop and candidates['props']: selected_prop = candidates['props'][0]

    selected_batt = candidates['batteries'][0] if candidates['batteries'] else None
    return { "motor": selected_motor, "prop": selected_prop, "batt": selected_batt, "esc": None, "stack": None }

def calculate_physics_profile(drone_class, frame, motor, batt, prop):
    name = frame['model_name'].lower()
    rotor_count = 6 if ("hex" in name or "x6" in name) else 4
    w_frame = parse_weight_to_kg(frame.get('specs', {}).get('Weight')) or 0.4
    w_motor = parse_weight_to_kg(motor.get('specs', {}).get('weight')) or 0.05
    w_batt = parse_weight_to_kg(batt.get('specs', {}).get('weight_g')) or 0.3
    total_mass_kg = w_frame + (w_motor * rotor_count) + w_batt + 0.15
    thrust_per_motor_n = 45.0 if drone_class == "HEAVY_LIFT" else 15.0
        
    return {
        "mass_kg": round(total_mass_kg, 3),
        "rotor_count": rotor_count,
        "motor_max_force_n": thrust_per_motor_n,
        "wheelbase_mm": extract_float(frame.get('specs', {}).get('wheelbase_mm')) or 250.0
    }

# --- USD GENERATOR ---
def generate_drone_usd(sku, entry, export_dir):
    if not HAS_USD: return
    file_path = os.path.join(export_dir, f"{sku}.usda")
    
    if os.path.exists(file_path): os.remove(file_path)
    stage = Usd.Stage.CreateNew(file_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    # Clean Root: just use the SKU, no /World prefix
    root_path = f"/{sku.replace('-', '_')}"
    root_prim = UsdGeom.Xform.Define(stage, root_path)
    stage.SetDefaultPrim(root_prim.GetPrim())
    
    phys_config = entry['technical_data']['physics_config']
    
    # Physics API
    mass_api = UsdPhysics.MassAPI.Apply(root_prim.GetPrim())
    mass_api.CreateMassAttr(phys_config['mass_kg'])
    
    rigid_api = UsdPhysics.RigidBodyAPI.Apply(root_prim.GetPrim())
    rigid_api.CreateRigidBodyEnabledAttr(True)

    # Geometry
    body_path = f"{root_path}/Body"
    body_mesh = UsdGeom.Cube.Define(stage, body_path)
    body_mesh.CreateSizeAttr(0.15)
    body_mesh.AddScaleOp().Set(Gf.Vec3f(1.0, 0.4, 0.2))
    
    visuals = entry['technical_data']['visuals']
    hex_color = visuals.get('primary_color_hex', '#555555').lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    body_mesh.CreateDisplayColorAttr([Gf.Vec3f(*rgb)])

    wb_meters = phys_config['wheelbase_mm'] / 1000.0
    radius = wb_meters / 2.0
    num_rotors = phys_config['rotor_count']
    
    for i in range(num_rotors):
        angle = (2 * math.pi / num_rotors) * i + (math.pi / 4)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        
        arm_path = f"{root_path}/Arm_{i}"
        arm = UsdGeom.Capsule.Define(stage, arm_path)
        arm.CreateHeightAttr(radius)
        arm.CreateRadiusAttr(0.01)
        arm.CreateAxisAttr("X") 
        
        arm_xform = UsdGeom.Xformable(arm)
        arm_xform.AddTranslateOp().Set(Gf.Vec3d(x/2, y/2, 0))
        arm_xform.AddRotateZOp().Set(math.degrees(angle))
        arm.CreateDisplayColorAttr([Gf.Vec3f(0.2, 0.2, 0.2)])

        motor_path = f"{root_path}/Motor_{i}"
        motor = UsdGeom.Cylinder.Define(stage, motor_path)
        motor.CreateHeightAttr(0.03)
        motor.CreateRadiusAttr(0.02)
        motor_xform = UsdGeom.Xformable(motor)
        motor_xform.AddTranslateOp().Set(Gf.Vec3d(x, y, 0.02))
        motor.CreateDisplayColorAttr([Gf.Vec3f(0.8, 0.1, 0.1)])

    stage.GetRootLayer().Save()
    print(f"   ⚡ Generated USD: {file_path}")

def main():
    try:
        with open('drone_arsenal.json', 'r') as f:
            data = json.load(f)
            inventory = data['components']
    except FileNotFoundError:
        print("Error: drone_arsenal.json not found.")
        return
        
    export_dir = os.path.abspath("usd_export")
    os.makedirs(export_dir, exist_ok=True)

    buckets = {
        "5_INCH": {"Motors": [], "Propellers": [], "Battery": [], "ESC": []},
        "7_INCH": {"Motors": [], "Propellers": [], "Battery": [], "ESC": []},
        "HEAVY_LIFT": {"Motors": [], "Propellers": [], "Battery": [], "ESC": []},
        "UNIVERSAL": {"FC_Stack": []}
    }
    
    frames = []
    for p in inventory:
        cat = p['category']
        size = determine_size_class(p)
        if size == "INVALID": continue
        if cat == 'Frame_Kit': frames.append((p, size))
        elif size in buckets and cat in buckets[size]: buckets[size][cat].append(p)
        elif cat == 'Battery':
             buckets["5_INCH"]["Battery"].append(p) 
             buckets["HEAVY_LIFT"]["Battery"].append(p)

    catalog_output = []
    print(f"🏭 Manufacturing Fleet from {len(frames)} frames...")
    
    for frame, size_class in frames:
        if size_class == "UNIVERSAL": size_class = "5_INCH"
        cands = {
            "motors": buckets[size_class]["Motors"],
            "props": buckets[size_class]["Propellers"],
            "batteries": buckets[size_class]["Battery"],
            "escs": buckets[size_class]["ESC"],
            "stacks": buckets["UNIVERSAL"]["FC_Stack"]
        }
        if not cands['motors'] or not cands['props']: continue

        res = simple_compatibility_match(frame, cands)
        
        if res['motor'] and res['prop'] and res['batt']:
            phys_data = calculate_physics_profile(size_class, frame, res['motor'], res['batt'], res['prop'])
            sku = f"DRONE-{uuid.uuid4().hex[:6].upper()}"
            entry = {
                "sku_id": sku,
                "model_name": f"Custom {size_class} - {frame['model_name'][:20]}",
                "class": size_class,
                "components": {"frame": frame['model_name'], "motor": res['motor']['model_name']},
                "technical_data": {"physics_config": phys_data, "visuals": frame.get('visuals', {'primary_color_hex': '#555555'})},
                "price_est": 0
            }
            catalog_output.append(entry)
            generate_drone_usd(sku, entry, export_dir)

    with open('drone_catalog.json', 'w') as f:
        json.dump(catalog_output, f, indent=2)

    print(f"\n✅ SUCCESS: Generated {len(catalog_output)} drones.")

if __name__ == "__main__":
    main()