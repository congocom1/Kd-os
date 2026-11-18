# KD capability upgrade from awesome-llm-apps

Source library inspected: `/home/hermes/awesome-llm-apps`.
Integration checkout: `/home/hermes/.cline/worktrees/ec023/Mark-LVI-main`.

## Delivered: offline Dependency Doctor

The actual Apache-2.0 Dependency Doctor utility is vendored under
`core/vendor/dependency_doctor/`, with license, author attribution and checksum.
KD's adapter adds path restrictions, input limits and an offline-only interface.
It checks obsolete Python backports, standard-library shadowing, unpinned
dependencies, duplicates and exact-pin conflicts. It does not install, rewrite,
execute project code, follow requirement includes, resolve dependencies or scan CVEs.

```sh
cd /home/hermes/.cline/worktrees/ec023/Mark-LVI-main
./kd deps requirements.txt
./kd deps frontend/package.json
./kd deps pyproject.toml
```

After restarting KD, the existing action loader discovers `dependency_audit`.
Example request: “Check this project's requirements.txt for dependency problems.”
Model tool selection still depends on the configured provider and tool budget.

Only the KD checkout is allowed by default. To approve another project, set
`KD_PROJECT_ROOTS=/absolute/project/path` in the local launch environment.
Multiple paths use the platform path separator (colon on Linux). The model cannot
expand the allowlist through tool parameters. Do not approve entire home folders.
Symlinks are resolved before containment checks. This is a same-user filesystem
boundary, not a sandbox against a concurrent hostile filesystem writer.

Results contain manifest paths and dependency names. The checker itself never
uses the network, but its result can enter the active assistant provider's context.
Use a local provider for private projects; this integration does not enforce the
application-wide cloud consent policy.

## Deliberately not imported wholesale

The library's local hybrid RAG example adds RAGLite, llama.cpp and Streamlit;
KD already has a knowledge_rag action and provider layer. A second uncoordinated
model stack would duplicate functionality and compete for VRAM. The collection's
cloud-agent and always-on examples were not executed or enabled. Their presence
does not imply KD has those capabilities. Further integrations need individual
dependency, permission and resource reviews.

No external source folder edits, personal-data migrations, package installs or
credentials were needed for this capability. Git remains unavailable because the
worktree metadata points to the missing primary checkout. Rollback: remove the
new adapter/action/vendor/tests/docs and the `deps` case in the KD launcher.