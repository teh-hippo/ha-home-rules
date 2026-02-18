# CHANGELOG


## v1.0.15 (2026-02-18)

### Bug Fixes

- Standardise CI tooling to uv, ruff, mypy strict
  ([`cf06b53`](https://github.com/teh-hippo/ha-home-rules/commit/cf06b53c7d6d8e9d8850adb67ce599a4c58d4fd6))

### Continuous Integration

- Pin Python 3.13 via .python-version for uv
  ([`ced1afb`](https://github.com/teh-hippo/ha-home-rules/commit/ced1afb5dac800391f19be1e5be4662d8c0072ab))

- Standardise tooling — uv, ruff, mypy strict, PSR, dependabot
  ([`3a748ca`](https://github.com/teh-hippo/ha-home-rules/commit/3a748ca4e9c58b8e73510a910ca89e889f9204d6))


## v1.0.14 (2026-02-18)

### Bug Fixes

- Note compact runtime footprint
  ([`c2ef187`](https://github.com/teh-hippo/ha-home-rules/commit/c2ef18700140adcbf8c68b2a23c5c351a3cee894))

### Refactoring

- Reduce runtime LOC by 30%
  ([`94fe3a0`](https://github.com/teh-hippo/ha-home-rules/commit/94fe3a0c1952291db6a3b4b2290e0edb73ef615a))


## v1.0.13 (2026-02-18)

### Bug Fixes

- Tighten README and release guidance
  ([`61665f9`](https://github.com/teh-hippo/ha-home-rules/commit/61665f97ad0f0888fa40327147fe3b941dc7c057))


## v1.0.12 (2026-02-18)

### Bug Fixes

- Align HA metadata and options diagnostics APIs
  ([`1060da4`](https://github.com/teh-hippo/ha-home-rules/commit/1060da4ffc050f9d134adc6bac4a5ff594e64300))

### Continuous Integration

- Make HACS brands check non-blocking
  ([`e75edf0`](https://github.com/teh-hippo/ha-home-rules/commit/e75edf0abf84fdf99d68b3a047ed40cbfe3955c9))

### Refactoring

- Share base entity metadata setup
  ([`6e65954`](https://github.com/teh-hippo/ha-home-rules/commit/6e65954262d33b1566eadfaed27f04a47e63b652))

- Store control mode as single enum field
  ([`6d5d861`](https://github.com/teh-hippo/ha-home-rules/commit/6d5d8610d2ba813dcef164985b5a557720d56459))

- Unify turn-on decision and reason logic
  ([`456d182`](https://github.com/teh-hippo/ha-home-rules/commit/456d18242b4a1fd3203c9a589a85c601ca7650d8))

### Testing

- Cover config flow lifecycle and diagnostics
  ([`c1de354`](https://github.com/teh-hippo/ha-home-rules/commit/c1de3548eacc99e2eb999f485935309966e704b0))


## v1.0.11 (2026-02-18)

### Bug Fixes

- Explicit startup state reconciliation after restart
  ([`c45db59`](https://github.com/teh-hippo/ha-home-rules/commit/c45db5957fce08ed0381f0ecc58145e1cb8d4c25))


## v1.0.10 (2026-02-18)

### Bug Fixes

- Timer countdown sensor now ticks in real-time
  ([`36c1890`](https://github.com/teh-hippo/ha-home-rules/commit/36c1890bc595929bf50dd4af670e55391efa7c17))

### Continuous Integration

- Gate release on validate workflow success
  ([`80baa5d`](https://github.com/teh-hippo/ha-home-rules/commit/80baa5d0928d35d5002493301e401beb55486499))

### Documentation

- Add Development section to README
  ([`76788b8`](https://github.com/teh-hippo/ha-home-rules/commit/76788b85d0371c914bb254c056e47d0b63c694c0))


## v1.0.9 (2026-02-18)

### Bug Fixes

- Resolve mypy errors missed by local checks; fix check.sh to use uv
  ([`d62b548`](https://github.com/teh-hippo/ha-home-rules/commit/d62b54891154357073a2c0d11529cf4284cfd036))

### Chores

- Add uv.lock to .gitignore
  ([`078e5c2`](https://github.com/teh-hippo/ha-home-rules/commit/078e5c21131548df1399d0a36bdfd9fdc548bd17))


## v1.0.8 (2026-02-17)

### Features

- Add timer countdown sensor
  ([`c6ca3ca`](https://github.com/teh-hippo/ha-home-rules/commit/c6ca3ca9256ece01502df4f45418eccb0b9b3570))


## v1.0.7 (2026-02-15)

### Bug Fixes

- Trigger semantic release for integration updates
  ([`ee3c758`](https://github.com/teh-hippo/ha-home-rules/commit/ee3c75838f8990b88c25e9af06d77dce97da2afb))

### Refactoring

- Deduplicate validation, remove dead code
  ([`875afa6`](https://github.com/teh-hippo/ha-home-rules/commit/875afa64ec6ff8aab0d42051fc80bb5e9e1b0812))

- Humanize no-change action output
  ([`0156252`](https://github.com/teh-hippo/ha-home-rules/commit/0156252f19bdab9ef3a8288912f2b1f3be0d84c4))


## v1.0.6 (2026-02-15)

### Bug Fixes

- **options**: Align entity settings
  ([`3bf0904`](https://github.com/teh-hippo/ha-home-rules/commit/3bf090469672f1aa7e15c96def670846c8751a80))


## v1.0.5 (2026-02-15)

### Bug Fixes

- **climate**: Never set auto mode
  ([`d151bf7`](https://github.com/teh-hippo/ha-home-rules/commit/d151bf7ae598c1b16dcd41869eeb6d00108e5f26))

### Chores

- Fix changelog generation
  ([`8bd6120`](https://github.com/teh-hippo/ha-home-rules/commit/8bd6120275fad34192db40c09ba50ee7f9069ddb))


## v1.0.4 (2026-02-15)

### Build System

- **deps**: Bump actions/checkout from 4 to 6
  ([`92ff773`](https://github.com/teh-hippo/ha-home-rules/commit/92ff7732b7499d394654d5f8caf95e925bbb97a8))

- **deps**: Bump actions/setup-python from 5 to 6
  ([`6a77c3e`](https://github.com/teh-hippo/ha-home-rules/commit/6a77c3e83e8c84df8b55a15c711af9c40c7e337d))

- **deps**: Bump github/codeql-action from 3 to 4
  ([`1162128`](https://github.com/teh-hippo/ha-home-rules/commit/11621286740a50d1011c2a1e6fedd638ed63cc3a))

- **deps**: Bump python-semantic-release/python-semantic-release
  ([`f2f961f`](https://github.com/teh-hippo/ha-home-rules/commit/f2f961f2bb2bb2cf8237a8bf196db5ca11149f00))

### Continuous Integration

- Improve dependabot release flow
  ([`3f889bc`](https://github.com/teh-hippo/ha-home-rules/commit/3f889bcf7e1a38b6d0a0a8b18a8ae71674b6f9e7))

### Documentation

- Simplify README
  ([`6c80995`](https://github.com/teh-hippo/ha-home-rules/commit/6c80995a84e7fdc7be5990fff7ca28378c941d59))


## v1.0.3 (2026-02-14)

### Bug Fixes

- Avoid Repairs for unknown sensors
  ([`f7eb9d9`](https://github.com/teh-hippo/ha-home-rules/commit/f7eb9d922a2fab4b4a3b43232cc178753f4c7766))


## v1.0.2 (2026-02-14)

### Bug Fixes

- Ignore unknown sensor states
  ([`4a6f571`](https://github.com/teh-hippo/ha-home-rules/commit/4a6f57157e8569a7a95df3e06c87c4326bca7d50))


## v1.0.1 (2026-02-14)

### Bug Fixes

- Satisfy hassfest manifest schema
  ([`9d103fe`](https://github.com/teh-hippo/ha-home-rules/commit/9d103fe352ec60cf65c3a12ebd14ab28fa4ecf87))


## v1.0.0 (2026-02-14)

### Features

- Improve options UX\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
  ([`5b792bc`](https://github.com/teh-hippo/ha-home-rules/commit/5b792bcb250bdfa6b0898b73fd99b9e15d9aabcb))

- Improve UI and history
  ([`9abe7f2`](https://github.com/teh-hippo/ha-home-rules/commit/9abe7f2b65d1003f91a29288d4faf4fc05fd8428))

### Breaking Changes

- Replaced the enabled/aggressive/dry-run/notifications switches with select.home_rules_control_mode
  and options-based notifications.


## v0.4.1 (2026-02-14)

### Bug Fixes

- Handle unavailable input entities
  ([`5a7895f`](https://github.com/teh-hippo/ha-home-rules/commit/5a7895fbbf619ceaf48421e7cd87ec87b4fd0dca))


## v0.4.0 (2026-02-14)

### Bug Fixes

- Prevent dry-run evaluation failure
  ([`06096d6`](https://github.com/teh-hippo/ha-home-rules/commit/06096d61b0fcdc9dbba009eb8249901286f904ec))

### Features

- Add optional notifications
  ([`9255906`](https://github.com/teh-hippo/ha-home-rules/commit/92559061c9f5ef090b1725b2fa9d71050bd15d04))


## v0.3.1 (2026-02-14)

### Bug Fixes

- Stable sensor object ids
  ([`bdd1cc5`](https://github.com/teh-hippo/ha-home-rules/commit/bdd1cc5a3ad6b0a7987ea1e714037d13407efc8a))


## v0.3.0 (2026-02-14)

### Features

- Expose automation-focused sensors
  ([`49ece02`](https://github.com/teh-hippo/ha-home-rules/commit/49ece025d1d74ea5ae3c231536ca85927ece15ee))


## v0.2.1 (2026-02-14)

### Bug Fixes

- Stable entity ids
  ([`3eebbe8`](https://github.com/teh-hippo/ha-home-rules/commit/3eebbe8aa74df1e297bbfb472ff24c1cb6827ae7))

### Chores

- Add @2x branding assets
  ([`7c01890`](https://github.com/teh-hippo/ha-home-rules/commit/7c0189072592c9e97c0ce03b69a5715539b4d5e6))


## v0.2.0 (2026-02-14)

### Chores

- Improve HACS and docs
  ([`c4f69ee`](https://github.com/teh-hippo/ha-home-rules/commit/c4f69eea467daf1bcc870113b5fcea673cc98c81))

- Make CI green
  ([`bc8077a`](https://github.com/teh-hippo/ha-home-rules/commit/bc8077aa0ea2307aba5c1d3011c3a0fc34c713a9))

### Continuous Integration

- Enforce HACS validation
  ([`ca28fa0`](https://github.com/teh-hippo/ha-home-rules/commit/ca28fa012819b07787a21289befb7892e9a71f0b))

- Fix HACS validation
  ([`bace038`](https://github.com/teh-hippo/ha-home-rules/commit/bace0381c547e270df44c75b58020ad63c5b2639))

- Fix hassfest and hacs ignore
  ([`9a8ad5a`](https://github.com/teh-hippo/ha-home-rules/commit/9a8ad5aa66ba34d80b8912ca59575cfac6e776db))

- Make HACS informational
  ([`497b55b`](https://github.com/teh-hippo/ha-home-rules/commit/497b55b439c3552876ebf19c925512310f970b02))

- Make HACS non-blocking
  ([`ef66122`](https://github.com/teh-hippo/ha-home-rules/commit/ef66122ecb55d4c3612ccb643c5bc519c700eafd))

- Silence unfixable HACS checks
  ([`7e3d465`](https://github.com/teh-hippo/ha-home-rules/commit/7e3d465ff1725b9a9ce29eacfde4df80f5c0d7c1))

- Stabilize HACS validation
  ([`e02969b`](https://github.com/teh-hippo/ha-home-rules/commit/e02969bea32f0bf1784a349769dd77b7f8157879))

### Documentation

- Add install and migration steps
  ([`532e1cc`](https://github.com/teh-hippo/ha-home-rules/commit/532e1ccd6593610f6e5dad125b1ac43e3d6f4f3d))

### Features

- Safer setup UX
  ([`e3360ed`](https://github.com/teh-hippo/ha-home-rules/commit/e3360eddb49dfc3d0e1386bd750e032bec443b9f))

### Testing

- Expand rules parity coverage
  ([`e06ec62`](https://github.com/teh-hippo/ha-home-rules/commit/e06ec6273d2e363be2fce910b9931d999e796b60))


## v0.1.0 (2026-02-13)

- Initial Release
