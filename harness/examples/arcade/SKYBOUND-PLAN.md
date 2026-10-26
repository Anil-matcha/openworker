# Skybound Carrier — implementation and qualification

Working branch: `feat/arcade-flagship`, pushed to private and sdk remotes.
No hub, accounts, remote downloads, shell tools, or online assets in this phase.

## Sequence

1. Extend bounded project snapshots with binary image (PNG/WebP/JPEG), WAV/OGG
   audio and self-contained GLB assets. Preserve existing text-only hashes and
   versions. Binary values are explicit in draft JSON; revision files contain
   real bytes. Validate signatures, per-file/project limits and relative paths.
2. Keep preview isolation: only same-project resources, correct MIME types,
   opaque sandbox, no native bridge or external network. Add trusted user file
   import with staged draft semantics, metadata inspection, and byte-correct ZIP
   export. Models see asset metadata, never binary dumps.
3. Bundle pinned GLTFLoader and its needed utility with Three.js. Create original
   assets: a simple animated courier GLB, generated sky artwork, sprite texture,
   synthesized sound files. Keep asset licenses/provenance with remixes.
4. Build Skybound Carrier: coherent floating-garden art direction, a finite first
   delivery run, lanes/jump/slide, collectibles, obstacles, clear tutorial,
   win/loss, pause/restart, mute, quality choice, keyboard and touch controls.
   Geometry and objects are reused; no unbounded infinite allocation.
5. Integrate featured starter; test original/remix/restore/export, binary
   tampering and boundaries, deterministic game logic, actual browser/Electron
   gameplay, and packaged Mac. Existing games must remain intact.

## Acceptance and limits

- Start and play offline, without a model or key. All assets copied on remix.
- Agent modifies source/config around curated assets using existing approvals.
- Import cannot silently publish or overwrite an approved revision.
- Original, remix and historical snapshots remain independent.
- Validate real gameplay and graphics load, not just a successful build.
- This is a stylized browser 3D game, not AAA output or a claim of NVIDIA
  hardware qualification. No external asset generation service added to Arcade.

## Progress

- [x] Inspect existing project/storage/preview boundaries and agree on worktree.
- [x] Binary assets and preview/export/import support.
- [x] Original game and bundled assets.
- [x] Storage, real-harness, gameplay and packaged-app qualification.
- [x] Document results; tested changes are ready for the coordinated push to both remotes.
