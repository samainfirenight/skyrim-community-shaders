# Community Shaders 1.9.1 on Skyrim 1.6.353

Status: investigation infrastructure prepared; no compatibility fix or working
1.6.353 binary has been confirmed. A successful build alone does not change
that status.

The source base is the unmodified upstream 1.9.1 release,
`265c28f53767e94dac1c0c3b211a0aa37d8ec396`. Keep upstream feature versions and
Effects11 support. Use its matching shader and feature assets when testing.
No Skyrim update or local compiler installation is part of this workflow.

## Evidence and open questions

- The supplied SKSE log reports that Community Shaders 1.9.1 loads on SKSE 2.1.5.
- The supplied crash report shows a null read at SkyrimSE.exe RVA `0x6ED10E`
  (`41034 + 0xAE`) during cell entry. Community Shaders does not appear in the
  reported call stack. This does not establish a Community Shaders hook as the
  cause, nor rule one out.
- The supplied CS log reports older Terrain Blending, Terrain Helper and Terrain
  Variation assets; Effects11 is disabled because its feature INI is absent.
  These are separate installation findings, not a confirmed crash diagnosis.
- Grass Collision adds a main-update call hook at AE ID `36564 + 0xC26`, absent
  in CS 1.4.7. Its instruction bytes and original target on 1.6.353 need review.
- Other fixed-offset calls, raw patches, vtable layouts and interactions with
  other loaded native plugins also need review. Do not invent replacement
  offsets or equate an opcode match with correct semantics.

## Offline review

The exact game executable is needed to inspect its original instructions.
Keep it and all personal logs outside the repository. The pinned CommonLib
source includes a 1.6.353 Address Library fixture for resolving the source IDs.

Run `python tools/compat/audit_legacy_calls.py --exe /private/SkyrimSE.exe
--output /private/cs-353-calls.json` on the analysis machine. Without `--exe`,
the script inventories the source locations but marks them unverified.
Reports list unparsed expressions and exclude neither them nor raw patches
from the remaining review. This script never modifies game files.

## Remote compilation

`.github/workflows/build-legacy-ae.yaml` builds this compatibility branch on a
GitHub Windows runner. It uses the upstream compiler/dependency setup and
packages the DLL, matching PDB and 1.9.1 assets, including Effects11. Devbench
integration is disabled to avoid the absent-host message noise in the supplied
log; this does not change Effects11 support. No source gameplay hooks are
changed by the infrastructure commit.

The output is deliberately labelled an investigation package. Review the
identified call sites and implement justified compatibility edits before
calling any resulting binary a 1.6.353 backport. In-game save/new-game entry
and rendering tests remain necessary after the build succeeds.
