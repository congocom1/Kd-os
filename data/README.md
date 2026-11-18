# Shared Data Workspace

This directory is the shared data workspace for the Mark-LVI monorepo.

## Layout

| Subdirectory | Purpose |
|--------------|---------|
| `cache/`     | Runtime caches, downloaded tiles, temporary model artifacts. Safe to delete. |
| `images/`    | Screenshots, renders, and image assets produced by the apps. |
| `logs/`      | Application and server logs. |
| `shared/`    | Cross-application datasets, configuration exports, and persisted state. |

## Notes

- Do not commit large binary files here. Use `assets/` for committed binary assets.
- The contents of `cache/` and `logs/` are ignored by Git.
- Docker Compose mounts this directory into the JARVIS container at `/app/data`.
