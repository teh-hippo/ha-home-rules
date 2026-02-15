# CHANGELOG


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
