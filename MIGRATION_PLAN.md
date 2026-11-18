# JARVIS-God's View Migration Plan

## Goal
Make JARVIS the single application that contains and manages God's View functionality, eliminating the need for separate browser windows and separate server processes.

## Current Architecture
- **God's View**: Standalone Vite app on port 4174, MCP server at /mcp endpoint
- **JARVIS**: Python app with `actions/globe.py` adapter that communicates via HTTP to the MCP server
- **Integration**: JARVIS sends JSON-RPC requests to God's View MCP; God's View returns data/links

## Migration Steps

### Phase 1: Stabilize the Bridge (Current State - DONE)
- Globe adapter tests pass (5/5)
- Globe server running on 127.0.0.1:4174
- 29 tools available via MCP
- Status action with `live_feeds_verified: False`

### Phase 2: JARVIS-Managed God's View Server
**Files to modify/create:**
- `launch.sh` - Start God's View server as background process if not running
- `actions/globe.py` - Add `start_server` and `stop_server` actions
- `core/kernel_init.py` - Ensure server starts with JARVIS

**Actions to add:**
- `globe:start` - Start God's View server on port 4174 (if not running)
- `globe:stop` - Stop God's View server
- `globe:status` - Check if server is running (already exists)

**Benefit:** JARVIS controls the lifecycle; no separate "open globe" window needed.

### Phase 3: Consolidate UI into JARVIS
**Files to create/modify:**
- `actions/globe_panels.py` - JARVIS UI panels for God's View data
- `ui.py` - Integrate globe views into main JARVIS UI
- `dashboard/` - Merge God's View dashboard panels

**UI Components:**
- Globe visualization panel (using existing shader/GL)
- Tool results display panel
- Share/view-link panel
- Status/health monitoring panel

**Benefit:** All God's View data appears within JARVIS, not separate browser windows.

### Phase 4: Migrate Core Tools to JARVIS Python
**Priority tools (high-impact, feasible to port):**
1. `get_earthquakes` - Static data, easy to port
2. `get_active_fires` - API-driven, moderate  
3. `get_weather` - API-driven, moderate
4. `get_recent_launches` - Space API, moderate
5. `search_places` - Geocoding, moderate

**Approach:**
- Port JavaScript query functions to Python
- Or wrap them as JARVIS actions calling the God's View MCP
- Replace JS implementations gradually

**Files:**
- `actions/earthquakes.py` - New JARVIS action
- `actions/weather.py` - New JARVIS action
- etc.

### Phase 5: Unified MCP Interface
**Create:** `actions/mcp_bridge.py`
- Single MCP client used by all JARVIS actions
- Automatic server detection/health-check
- Fallback modes if server unavailable

**Modify:** `actions/globe.py` to use unified bridge

### Phase 6: UI Improvements from JARVIS
**Enhance JARVIS UI with:**
- God's View globe in main window (not separate browser)
- Tool results in side panels
- Share links as JARVIS action outputs
- Keyboard shortcuts for common globe queries
- Voice commands: "Show earthquakes near Japan", "Find aircraft in area"

**Files:**
- `ui.py` - Add globe tab/panel
- `actions/` - Voice command handlers
- `core/` - Integration with LLM tool calling

## Success Criteria
1. JARVIS starts/stops God's View server
2. All 30+ God's View tools accessible from JARVIS actions
3. God's View data displays in JARVIS UI panels (not browser windows)
4. Voice commands control globe functions
5. No duplicate windows - everything in JARVIS

## Rollback Plan
- Keep God's View standalone launch-jarvis.sh script
- Maintain MCP HTTP endpoint at port 4174
- JARVIS actions fall back to HTTP calls if server managed separately

## Next Immediate Steps
1. Add `globe:start` and `globe:stop` actions to JARVIS
2. Create JARVIS UI panel for globe visualization
3. Test that JARVIS can start God's View server and query tools
4. Begin porting 2-3 high-impact tools to JARVIS Python actions