from omni.isaac.kit import SimulationApp
simulation_app = SimulationApp({"headless": False})

import omni
from omni.isaac.core import World
from omni.isaac.core.prims import RigidPrimView
from omni.isaac.core.utils.stage import add_reference_to_stage
import numpy as np
import json
import os

# --- CONFIGURATION ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
USD_EXPORT_DIR = os.path.join(CURRENT_DIR, "usd_export")
CATALOG_PATH = os.path.join(CURRENT_DIR, "drone_catalog.json")

# PD Controller Gains
KP = 15.0 
KD = 10.0

def main():
    world = World()
    world.scene.add_default_ground_plane()
    
    if not os.path.exists(CATALOG_PATH):
        print(f"❌ Error: Catalog not found at {CATALOG_PATH}")
        return

    with open(CATALOG_PATH, "r") as f:
        fleet_data = json.load(f)

    print(f"--> 🛸 Spawning {len(fleet_data)} drones...")

    # Data arrays for batch processing
    target_heights = []
    masses = []
    
    for i, drone_spec in enumerate(fleet_data):
        sku = drone_spec['sku_id']
        usd_filename = f"{sku}.usda"
        usd_path = os.path.join(USD_EXPORT_DIR, usd_filename)
        
        if not os.path.exists(usd_path):
            print(f"   ⚠️  Skipping {sku}: Missing USD file")
            continue

        # Add Reference (Geometry)
        prim_path = f"/World/Drone_{i}"
        add_reference_to_stage(usd_path=usd_path, prim_path=prim_path)
        
        # Store metadata for controller
        target_heights.append(1.0 + (i * 0.5))
        masses.append(drone_spec['technical_data']['physics_config']['mass_kg'])

        # Set initial transform manually since we aren't using RigidPrim wrapper loop yet
        # We will let the View handle the binding, but we need them not to overlap at spawn
        # Note: XForm operations here are done via USD directly usually, but View will pick up default
        # For simplicity, we rely on the View initialization reset below.

    # --- BATCH VIEW INITIALIZATION ---
    # This matches ALL prims named /World/Drone_*
    # reset_xform_properties=False ensures we don't zero out scale from USD
    drone_view = RigidPrimView(prim_paths_expr="/World/Drone_*", name="drone_fleet", reset_xform_properties=False)
    
    # We must add the view to the scene for it to initialize
    world.scene.add(drone_view)
    
    # Reset and Initialize Physics
    world.reset()

    # Set Initial Positions (Spread them out)
    num_drones = drone_view.count
    if num_drones == 0:
        print("❌ No drones found in stage!")
        simulation_app.close()
        return

    indices = np.arange(num_drones)
    initial_pos = np.zeros((num_drones, 3))
    for i in range(num_drones):
        initial_pos[i] = [i * 2.0, 0, 0.5]
    
    drone_view.set_world_poses(positions=initial_pos, indices=indices)

    # Controller State
    prev_errors = np.zeros(num_drones)
    target_heights = np.array(target_heights[:num_drones])
    masses = np.array(masses[:num_drones])

    print("--> 🚀 Physics Simulation Started. Press Ctrl+C in terminal to stop.")

    while simulation_app.is_running():
        world.step(render=True)
        if not world.is_playing(): continue
        
        # 1. Get Batch State (All Drones at once)
        # Shape: (num_drones, 3)
        current_transforms, _ = drone_view.get_world_poses()
        current_z = current_transforms[:, 2]
        
        # 2. Vectorized PD Control
        errors = target_heights - current_z
        derivatives = errors - prev_errors
        prev_errors = errors
        
        # 3. Calculate Forces
        # F = mg + Kp*e + Kd*de
        gravity_offsets = masses * 9.81
        throttles = gravity_offsets + (errors * KP) + (derivatives * KD)
        
        # Construct Force Matrix (N, 3) -> Applying only to Z axis
        forces = np.zeros((num_drones, 3))
        forces[:, 2] = throttles
        
        # 4. Apply Forces Batch
        drone_view.apply_forces(forces, is_global=True)

    simulation_app.close()

if __name__ == "__main__":
    main()