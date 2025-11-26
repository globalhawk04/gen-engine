# FILE: seed_arsenal.py
import asyncio
import json
import os
import random
from app.services.ai_service import call_llm_for_json
from app.services.fusion_service import fuse_component_data
from app.prompts import (
    RANCHER_PERSONA_INSTRUCTION, 
    ARSENAL_ENGINEER_INSTRUCTION, 
    ARSENAL_SOURCER_INSTRUCTION,
    ARSENAL_SCOUT_INSTRUCTION
)

ARSENAL_FILE = "drone_arsenal.json"

# --- AGENT 1: THE RANCHER (Returns a LIST of missions) ---
async def agent_rancher_needs():
    print("\n🤠 AGENT 1: The Rancher is defining the fleet...")
    
    # We trigger the prompt which now enforces a dictionary wrapper {"missions": []}
    result = await call_llm_for_json(
        "Define the specialized drone fleet for the ranch.", 
        RANCHER_PERSONA_INSTRUCTION
    )
    
    if not result:
        print("   ⚠️  LLM returned None. Check API Key or parse logic.")
        return []

    # Handle the wrapper logic safely
    if isinstance(result, dict):
        if "missions" in result:
            return result["missions"]
        else:
            print(f"   ⚠️  LLM returned dict but missing 'missions' key: {result.keys()}")
            return []
            
    # Fallback if AI ignored instructions and sent a raw list anyway
    if isinstance(result, list):
        return result
        
    return []

# --- AGENT 2: THE ENGINEER (Builder Track) ---
async def agent_engineer_parts(mission_profile):
    mission_name = mission_profile.get("mission_name", "Unknown Mission")
    print(f"\n👷 AGENT 2 (Engineer): Designing custom build for {mission_name}...")
    
    context = json.dumps(mission_profile)
    return await call_llm_for_json(
        f"MISSION PROFILE: {context}", 
        ARSENAL_ENGINEER_INSTRUCTION
    )

# --- AGENT 2.5: THE MARKET SCOUT (Buyer Track) ---
async def agent_market_scout(mission_profile):
    mission_name = mission_profile.get("mission_name", "Unknown Mission")
    print(f"\n🕵️ AGENT 2.5 (Scout): Searching pre-built options for {mission_name}...")
    
    context = json.dumps(mission_profile)
    # Expects {"Complete_Drone": ["Model A", "Model B"]}
    return await call_llm_for_json(
        f"MISSION PROFILE: {context}", 
        ARSENAL_SCOUT_INSTRUCTION
    )

# --- AGENT 3: THE SOURCER ---
async def agent_sourcer_queries(parts_structure, mission_name):
    print(f"\n🔎 AGENT 3 (Sourcer): Generating queries for {mission_name} items...")
    
    context_list = []
    for category, models in parts_structure.items():
        if isinstance(models, list):
            for m in models:
                context_list.append(f"{category}: {m}")
    
    context_str = "\n".join(context_list)
    
    response = await call_llm_for_json(
        f"COMPONENT LIST: {context_str}", 
        ARSENAL_SOURCER_INSTRUCTION
    )
    return response.get("queries", []) if response else []

# --- UTILS ---
def load_arsenal():
    if os.path.exists(ARSENAL_FILE):
        try:
            with open(ARSENAL_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"components": []}

def save_to_arsenal(new_item, tags, item_type="component"):
    db = load_arsenal()
    
    # Check for duplicates based on model name
    for existing in db['components']:
        if existing['model_name'] == new_item['product_name']:
            print(f"      ⚠️  Known Item: {new_item['product_name']}. Updating tags.")
            if "tags" not in existing: existing["tags"] = []
            for t in tags:
                if t not in existing["tags"]: existing["tags"].append(t)
            
            with open(ARSENAL_FILE, "w") as f: json.dump(db, f, indent=2)
            return

    entry = {
        "type": item_type, # "component" or "complete_drone"
        "category": new_item['part_type'],
        "model_name": new_item['product_name'],
        "price_est": new_item['price'],
        "specs": new_item['engineering_specs'],
        "image_url": new_item['reference_image'],
        "source_url": new_item['source_url'],
        "verified": True,
        "tags": tags 
    }
    
    db['components'].append(entry)
    
    with open(ARSENAL_FILE, "w") as f:
        json.dump(db, f, indent=2)
    print(f"      💾 Saved to {ARSENAL_FILE}")

# --- MAIN EXECUTION FLOW ---
async def run_seeder():
    print("🏭 OPENFORGE ARSENAL SEEDER (BUILD VS BUY MODE) INITIALIZED")
    print("==========================================================")
    
    # 1. Get List of Missions (Rancher)
    missions = await agent_rancher_needs()
    if not missions: 
        print("❌ Rancher Agent failed to generate missions."); return
    
    print(f"   -> Defined {len(missions)} distinct missions.")

    # 2. Iterate through EACH mission
    for mission in missions:
        m_name = mission.get("mission_name", "General")
        print(f"\n🚀 STARTING MISSION CAMPAIGN: {m_name}")
        print(f"   Goal: {mission.get('primary_goal')}")
        
        # --- TRACK 1: CUSTOM BUILD (The Engineer) ---
        build_parts = await agent_engineer_parts(mission)
        
        # --- TRACK 2: OFF-THE-SHELF (The Scout) ---
        buy_drones = await agent_market_scout(mission)
        
        # Merge lists for the Sourcer
        full_target_list = {}
        if build_parts: full_target_list.update(build_parts)
        if buy_drones: full_target_list.update(buy_drones) # Adds "Complete_Drone": [...]

        if not full_target_list:
            print(f"   ❌ No targets identified for {m_name}. Skipping.")
            continue
            
        # B. Generate Queries for EVERYTHING
        query_list = await agent_sourcer_queries(full_target_list, m_name)
        if not query_list:
             print(f"   ❌ Sourcing failed for {m_name}. Skipping.")
             continue
        
        print(f"   -> Found {len(query_list)} targets (Parts & Pre-builts). Engaging Fusion Service...")

        # C. Fusion Search (Deep Recon)
        for i, item in enumerate(query_list):
            category = item['part_type']
            model = item['model_name']
            search_query = item['search_query']
            
            # Determine Item Type for DB storage
            item_type = "complete_drone" if category == "Complete_Drone" else "component"

            print(f"\n   ⚡ Processing [{i+1}/{len(query_list)}]: {model} ({item_type})...")
            
            # Rate Limiting
            sleep_time = random.uniform(5.0, 10.0)
            print(f"      💤 Sleeping {sleep_time:.1f}s...")
            await asyncio.sleep(sleep_time)
            
            # Strict Fusion Search
            result = await fuse_component_data(
                part_type=category, 
                search_query=search_query,
                search_limit=8, 
                min_confidence=0.80
            )
            
            if result and result.get('engineering_specs') and result.get('price'):
                 print(f"      ✅ Verified: {model}. Saving...")
                 save_to_arsenal(result, tags=[m_name], item_type=item_type)
            else:
                 print(f"      ❌ Failed to verify: {model}")

    print("\n✅ All Mission Campaigns Complete. Arsenal Updated.")

if __name__ == "__main__":
    asyncio.run(run_seeder())