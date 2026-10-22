# Community Shaders 1.9.1 on Skyrim 1.6.353

Status: candidate 1 corrects the identified player cell-event-source layout
error. The correction has executable-level evidence; an in-game test is still
required before describing the resulting DLL as working on 1.6.353.

The source base is the upstream 1.9.1 release,
`265c28f53767e94dac1c0c3b211a0aa37d8ec396`. Keep upstream feature versions and
Effects11 support. Use its matching shader and feature assets when testing.
No Skyrim update or local compiler installation is part of this workflow.

## Evidence and open questions

### Candidate 1 correction

The pinned CommonLib `PlayerCharacter::AsBGSActorCellEventSource()` returns
`player + 0x2D8` on every AE runtime before 1.7.99. The supplied 1.6.353
executable's SetParentCell function (AE ID 40466, RVA `0x6C9D30`) instead
constructs the event-source pointer at `player + 0x2D0` (instructions at
`0x6C9D97` and `0x6C9DAC`) before calling SendEvent (ID 41034).

Community Shaders 1.9.1's Terrain Shadows feature uses that accessor during
DataLoaded. Writing event registrations eight bytes into the real event
source can replace array capacity/count fields instead of the intended
array pointer. The observed crash is inside SendEvent's pending-register
loop: a null buffer is dereferenced while the count is nonzero. This
matches the offset error and the first-cell-entry trigger.

Candidate 1 uses the verified `+0x2D0` event source for AE runtimes older
than 1.6.629. Other runtimes retain CommonLib's existing accessor. It keeps
the event listener and the new renderer features, including Effects11,
enabled; it does not add a general null-pointer skip to the engine.
CommunityShaders.log identifies candidate 1 and records the event-source
offset. On 1.6.353 the expected offset is `+0x2D0`.

### Other findings

- The supplied SKSE log reports that Community Shaders 1.9.1 loads on SKSE 2.1.5.
- The supplied crash report shows a null read at SkyrimSE.exe RVA `0x6ED10E`
  (`41034 + 0xAE`) during cell entry. Community Shaders does not appear in the
  reported call stack. This does not establish a Community Shaders hook as the
  cause, nor rule one out.
- The supplied CS log reports older Terrain Blending, Terrain Helper and Terrain
  Variation assets; Effects11 is disabled because its feature INI is absent.
  These are separate installation findings, not a confirmed crash diagnosis.
- Grass Collision adds a main-update call hook at AE ID `36564 + 0xC26`, absent
  in CS 1.4.7. The supplied executable confirms an E8 call at that location;
  it is not the event-source layout error identified above.
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
packages the DLL, matching PDB and 1.9.1 assets, including Effects11. It retains
the upstream developer-bridge configuration; the bridge remains inactive when
the optional devbench host is absent.

The output is deliberately labelled an investigation package until the in-game
save/new-game entry and rendering tests pass. Candidate 1 contains the targeted
event-registration correction described above.
