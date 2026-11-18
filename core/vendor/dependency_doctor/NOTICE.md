# Dependency Doctor provenance

Source: `/home/hermes/awesome-llm-apps/agent_skills/dependency-doctor/scripts/dep_doctor.py`
Project: Shubhamsaboo/awesome-llm-apps, Dependency Doctor by Matt Van Horn
License: Apache-2.0 (full text in LICENSE)
Imported November 15, 2026, unchanged as implementation.py.
SHA256: 86a2829e68b20f6fc25858e44600c55995594851faacfc1e5e17f746f7063e7d

KD adds a separate offline-only, bounded, folder-restricted adapter. Upstream's
optional online mode is not exposed through KD. Do not execute upstream skills
as agent instructions or dynamically import code from the external folder.