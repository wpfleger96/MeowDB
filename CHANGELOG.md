# Changelog

## [0.10.1](https://github.com/wpfleger96/MeowDB/compare/v0.10.0...v0.10.1) (2026-08-09)


### Bug Fixes

* **db:** use online backup API for pre-migration snapshot ([#100](https://github.com/wpfleger96/MeowDB/issues/100)) ([4a65b68](https://github.com/wpfleger96/MeowDB/commit/4a65b68c460b2ccb10b3d5fdcdbeeb4913ce3b44))

## [0.10.0](https://github.com/wpfleger96/MeowDB/compare/v0.9.1...v0.10.0) (2026-08-09)


### Features

* add multi-animal profiles with species-grouped sounds ([#93](https://github.com/wpfleger96/MeowDB/issues/93)) ([3e7b4e9](https://github.com/wpfleger96/MeowDB/commit/3e7b4e999599674075d3d2e6ff3c5279d436b032))


### Chores

* **deps:** Update python Docker tag to v3.14 ([#81](https://github.com/wpfleger96/MeowDB/issues/81)) ([543f0f8](https://github.com/wpfleger96/MeowDB/commit/543f0f8ed8e58e4bf18455f37ccb9b406c6c8607))


### Documentation

* document cross-repo deploy and S3 backup architecture in AGENTS.md ([#99](https://github.com/wpfleger96/MeowDB/issues/99)) ([55e8d36](https://github.com/wpfleger96/MeowDB/commit/55e8d36e2d6b2a0d0fcd4b7efd927deb3022c64e))

## [0.9.1](https://github.com/wpfleger96/MeowDB/compare/v0.9.0...v0.9.1) (2026-08-09)


### Bug Fixes

* **ui:** make About panel dismissable via X button and click-outside ([#96](https://github.com/wpfleger96/MeowDB/issues/96)) ([9d15efe](https://github.com/wpfleger96/MeowDB/commit/9d15efe20861dc525aeb9c10a49869479c050fc1))

## [0.9.0](https://github.com/wpfleger96/MeowDB/compare/v0.8.1...v0.9.0) (2026-08-09)


### Features

* add S3-primary storage for committed media ([#94](https://github.com/wpfleger96/MeowDB/issues/94)) ([d805d44](https://github.com/wpfleger96/MeowDB/commit/d805d449f001baab03e6e625a8285798ced0ae85))
* **ui:** replace sidebar version string with an About panel ([#95](https://github.com/wpfleger96/MeowDB/issues/95)) ([c83f681](https://github.com/wpfleger96/MeowDB/commit/c83f6817f0e0536d7ec28ae48460ff5b52cb5637))


### Chores

* **deps:** Lock file maintenance ([#82](https://github.com/wpfleger96/MeowDB/issues/82)) ([de6a311](https://github.com/wpfleger96/MeowDB/commit/de6a311e1c1e34f620d138c7f28db3dff41be3b4))
* **deps:** Lock file maintenance ([#83](https://github.com/wpfleger96/MeowDB/issues/83)) ([45959b1](https://github.com/wpfleger96/MeowDB/commit/45959b16f8529169e2b9ccf3bc385849be67ac97))
* **deps:** Lock file maintenance ([#85](https://github.com/wpfleger96/MeowDB/issues/85)) ([1d611a1](https://github.com/wpfleger96/MeowDB/commit/1d611a1e1becbec5ba8a28a359816b866c0e2c69))
* **deps:** Lock file maintenance ([#86](https://github.com/wpfleger96/MeowDB/issues/86)) ([6d742d8](https://github.com/wpfleger96/MeowDB/commit/6d742d8c059c5028b85c254b7c394cdf7bf55d1a))
* **deps:** Lock file maintenance ([#88](https://github.com/wpfleger96/MeowDB/issues/88)) ([20adeb0](https://github.com/wpfleger96/MeowDB/commit/20adeb096c8f8e9d3e157d236d6bd775e30071fc))
* **deps:** Lock file maintenance ([#89](https://github.com/wpfleger96/MeowDB/issues/89)) ([b14cc25](https://github.com/wpfleger96/MeowDB/commit/b14cc2503f54dcf69d4e5ae939b647925a0b2312))
* **deps:** Lock file maintenance ([#90](https://github.com/wpfleger96/MeowDB/issues/90)) ([ea62dd7](https://github.com/wpfleger96/MeowDB/commit/ea62dd7bfe6d2bf1d0ab4354d969869f990df58a))
* **deps:** Lock file maintenance ([#92](https://github.com/wpfleger96/MeowDB/issues/92)) ([10354f4](https://github.com/wpfleger96/MeowDB/commit/10354f427ffc119b310f6382bb9f2d17047e80b2))
* **deps:** Update astral-sh/setup-uv action to v8.3.2 ([#84](https://github.com/wpfleger96/MeowDB/issues/84)) ([f31b35f](https://github.com/wpfleger96/MeowDB/commit/f31b35f2e12243d7f7090eb098ee1147b1b42bde))
* **deps:** Update dependency @playwright/test to v1.62.1 ([#91](https://github.com/wpfleger96/MeowDB/issues/91)) ([cdff698](https://github.com/wpfleger96/MeowDB/commit/cdff698703e0271092212eac8cd7c260b50086b3))


### Continuous Integration

* sync CI workflow ([5c0f36a](https://github.com/wpfleger96/MeowDB/commit/5c0f36ac5f3c775b78c375c9911c197af6742722))
* sync CI workflow ([29e9e68](https://github.com/wpfleger96/MeowDB/commit/29e9e68a3c3082b1cb408c6276a1d8fcef0f1871))
* sync release workflow ([c14feef](https://github.com/wpfleger96/MeowDB/commit/c14feef0b6d6a4cfbc9b9e83494d59df6811af85))
* sync release workflow ([84a6cc9](https://github.com/wpfleger96/MeowDB/commit/84a6cc938b4798ed68ee8971b3166e53eb888ed4))

## [0.8.1](https://github.com/wpfleger96/MeowDB/compare/v0.8.0...v0.8.1) (2026-07-03)


### Bug Fixes

* harden staging path guard and simplify codebase ([#74](https://github.com/wpfleger96/MeowDB/issues/74)) ([25b394b](https://github.com/wpfleger96/MeowDB/commit/25b394b1b383785e2cdba191c796a90decc420f8))


### Performance Improvements

* fix CLS, LCP, and INP regressions on the play view ([#76](https://github.com/wpfleger96/MeowDB/issues/76)) ([9f3e4ba](https://github.com/wpfleger96/MeowDB/commit/9f3e4bae3e90b3fd15d0975e57ee07db8abc213e))


### Chores

* add perf to release-please changelog sections ([#77](https://github.com/wpfleger96/MeowDB/issues/77)) ([bc1a3db](https://github.com/wpfleger96/MeowDB/commit/bc1a3dbadf421a2d5e9a11d18292b751d941076e))


### Continuous Integration

* sync CI workflow ([f6ed6af](https://github.com/wpfleger96/MeowDB/commit/f6ed6af3215ba88f17d38615077e2ba04a73f45d))

## [0.8.0](https://github.com/wpfleger96/MeowDB/compare/v0.7.0...v0.8.0) (2026-07-02)


### Features

* add in-app Algorithm page rendering ALGORITHM.md ([#72](https://github.com/wpfleger96/MeowDB/issues/72)) ([ad9069c](https://github.com/wpfleger96/MeowDB/commit/ad9069ce8fd8a7ec95c9a291c3e064f1ef7c3a03))


### Chores

* **deps:** Lock file maintenance ([#70](https://github.com/wpfleger96/MeowDB/issues/70)) ([b4a04c9](https://github.com/wpfleger96/MeowDB/commit/b4a04c9d93e7f3b17ed921a596dd81afdda73e85))
* **deps:** Lock file maintenance ([#71](https://github.com/wpfleger96/MeowDB/issues/71)) ([36bd12a](https://github.com/wpfleger96/MeowDB/commit/36bd12a36c1bdb35106f255494135327f9a8b546))
* **deps:** Update dependency @playwright/test to v1.61.1 ([#69](https://github.com/wpfleger96/MeowDB/issues/69)) ([4a04aba](https://github.com/wpfleger96/MeowDB/commit/4a04abaf25a081eee0feb81a4e35b66f668dae62))
* sync pre-commit hook ([2604b67](https://github.com/wpfleger96/MeowDB/commit/2604b67e774e8f720faf28e008f01e183e6ddf4a))


### Documentation

* use numbered citations in the algorithm write-up ([#73](https://github.com/wpfleger96/MeowDB/issues/73)) ([a10b7d8](https://github.com/wpfleger96/MeowDB/commit/a10b7d89731241dfc4f06fe829b6cbcb3b4529c1))

## [0.7.0](https://github.com/wpfleger96/MeowDB/compare/v0.6.0...v0.7.0) (2026-06-29)


### Features

* add Replay button to re-play the last meow ([#66](https://github.com/wpfleger96/MeowDB/issues/66)) ([f948528](https://github.com/wpfleger96/MeowDB/commit/f94852855ee7f65c8613fb4b4b0cfd852be77bf6))

## [0.6.0](https://github.com/wpfleger96/MeowDB/compare/v0.5.3...v0.6.0) (2026-06-27)


### Features

* **similarity:** add PCEN, delta MFCCs, and k-NN uniqueness scoring ([#57](https://github.com/wpfleger96/MeowDB/issues/57)) ([53abf5a](https://github.com/wpfleger96/MeowDB/commit/53abf5a56a56f5ba7ef1fcb7629a06c3b69e2231))


### Continuous Integration

* sync CI workflow ([8317dee](https://github.com/wpfleger96/MeowDB/commit/8317dee219e3b24b3f7285cb3c9e2c2e47177dc5))
* sync CI workflow ([5f05b27](https://github.com/wpfleger96/MeowDB/commit/5f05b27515ddcb10a63b927337c15b0b48f54fa1))
* sync CI workflow ([5bc3309](https://github.com/wpfleger96/MeowDB/commit/5bc33092c57c846e16236f05d57f0bf652d0254b))
* sync release workflow ([2246b1e](https://github.com/wpfleger96/MeowDB/commit/2246b1e83c9da20526cad240449d69ba117633b9))
* sync release workflow ([86006f4](https://github.com/wpfleger96/MeowDB/commit/86006f4b0e07dbf39c54db43115c84802923b631))

## [0.5.3](https://github.com/wpfleger96/MeowDB/compare/v0.5.2...v0.5.3) (2026-06-27)


### Bug Fixes

* **docker:** install git for pydub git dependency in slim image ([#63](https://github.com/wpfleger96/MeowDB/issues/63)) ([a0ea10e](https://github.com/wpfleger96/MeowDB/commit/a0ea10ec2f656a7157e7f14dcab07300a2a642f4))

## [0.5.2](https://github.com/wpfleger96/MeowDB/compare/v0.5.1...v0.5.2) (2026-06-27)


### Bug Fixes

* **deps:** pin pydub to GitHub master; default export path to DATA_DIR ([#61](https://github.com/wpfleger96/MeowDB/issues/61)) ([94aa557](https://github.com/wpfleger96/MeowDB/commit/94aa557222d741cdbbb8a9fad25270a6fcff3471))

## [0.5.1](https://github.com/wpfleger96/MeowDB/compare/v0.5.0...v0.5.1) (2026-06-27)


### Bug Fixes

* **cli:** show truncation hint in list output; pin Dockerfile to Python 3.13 ([#59](https://github.com/wpfleger96/MeowDB/issues/59)) ([d672077](https://github.com/wpfleger96/MeowDB/commit/d672077f1c98f32476ba284da126c93ec06c19a2))

## [0.5.0](https://github.com/wpfleger96/MeowDB/compare/v0.4.0...v0.5.0) (2026-06-27)


### Features

* **cli:** add export and import commands for meow library transfer ([#58](https://github.com/wpfleger96/MeowDB/issues/58)) ([fe2bf7d](https://github.com/wpfleger96/MeowDB/commit/fe2bf7d4a0c3b6694740eff5a33b28e549c5dcae))


### Chores

* **deps:** Lock file maintenance ([#53](https://github.com/wpfleger96/MeowDB/issues/53)) ([01ee82b](https://github.com/wpfleger96/MeowDB/commit/01ee82bb7578de0104b9a5f6d672e17c19684d6b))
* **deps:** Lock file maintenance ([#55](https://github.com/wpfleger96/MeowDB/issues/55)) ([4989314](https://github.com/wpfleger96/MeowDB/commit/498931458a500a2297c8ff00e935041bcca371e9))
* **deps:** Lock file maintenance ([#56](https://github.com/wpfleger96/MeowDB/issues/56)) ([134ac3d](https://github.com/wpfleger96/MeowDB/commit/134ac3dab9948f2eb803534262ec2f1c6ab8a12a))
* **deps:** Update actions/checkout action to v7 ([#52](https://github.com/wpfleger96/MeowDB/issues/52)) ([e18230b](https://github.com/wpfleger96/MeowDB/commit/e18230be2b5135975a0461fd3e4f4d6650d8106c))

## [0.4.0](https://github.com/wpfleger96/MeowDB/compare/v0.3.0...v0.4.0) (2026-06-24)


### Features

* re-enable active service worker for PWA update propagation ([#51](https://github.com/wpfleger96/MeowDB/issues/51)) ([c23d908](https://github.com/wpfleger96/MeowDB/commit/c23d908c4448d0ee4c7072f00b40ba2c4b5d4c60))


### Bug Fixes

* move version string from play view to sidebar brand ([#49](https://github.com/wpfleger96/MeowDB/issues/49)) ([ae47138](https://github.com/wpfleger96/MeowDB/commit/ae4713837b5e673098cb58b4e5e3f2ca9712dca3))

## [0.3.0](https://github.com/wpfleger96/MeowDB/compare/v0.2.0...v0.3.0) (2026-06-23)


### Features

* add thumbs up/down feedback on play page ([#47](https://github.com/wpfleger96/MeowDB/issues/47)) ([058268c](https://github.com/wpfleger96/MeowDB/commit/058268c6b5fe0dcc468933252ecd0a28755cb5ea))


### Continuous Integration

* sync CI workflow ([d425f7a](https://github.com/wpfleger96/MeowDB/commit/d425f7aac1e858c1aec7d364931bea765426f763))

## [0.2.0](https://github.com/wpfleger96/MeowDB/compare/v0.1.0...v0.2.0) (2026-06-22)


### Features

* add meow uniqueness scoring and fix stats/session/photo bugs ([#18](https://github.com/wpfleger96/MeowDB/issues/18)) ([6be8949](https://github.com/wpfleger96/MeowDB/commit/6be8949ad287a9719decb606d9a1b0ec86cbe245))
* add password auth with session cookies and auth-aware UI ([#10](https://github.com/wpfleger96/MeowDB/issues/10)) ([0b460ab](https://github.com/wpfleger96/MeowDB/commit/0b460ab77196c3159e0b7959d69e9dbd8d554268))
* add password auth with session cookies and brute-force protection ([#9](https://github.com/wpfleger96/MeowDB/issues/9)) ([a094929](https://github.com/wpfleger96/MeowDB/commit/a0949295f7a2db04aae40422a879cd4b6473b87f))
* add Playwright E2E tests and ad-hoc screenshot capture ([#2](https://github.com/wpfleger96/MeowDB/issues/2)) ([66f0def](https://github.com/wpfleger96/MeowDB/commit/66f0defa0c2d31f1d920f798d928b16e143e4b96))
* audio cropper fixes, cat photos, and clip audio preservation ([#12](https://github.com/wpfleger96/MeowDB/issues/12)) ([cd59565](https://github.com/wpfleger96/MeowDB/commit/cd59565ff7f1c7532d7d6fc6dc7de00535da37f6))
* deploy MeowDB on Fly.io with Cloudflare ([#7](https://github.com/wpfleger96/MeowDB/issues/7)) ([6afab59](https://github.com/wpfleger96/MeowDB/commit/6afab591466e819ecb9bfd32522f4776e838696d))
* fix audio playback, add meow fields, clip editor UX, and db tools ([#5](https://github.com/wpfleger96/MeowDB/issues/5)) ([fa21f55](https://github.com/wpfleger96/MeowDB/commit/fa21f55897328e9b643167b3a70383e7f524267a))
* implement full MeowDB application ([#1](https://github.com/wpfleger96/MeowDB/issues/1)) ([4f652f7](https://github.com/wpfleger96/MeowDB/commit/4f652f76d173702b446919d49dde636e2463aa1e))
* **ingest:** accept video files and extract audio for clipping ([#21](https://github.com/wpfleger96/MeowDB/issues/21)) ([b1d453a](https://github.com/wpfleger96/MeowDB/commit/b1d453a3bf80566a605cfb77f2e5e72946f64f8f))
* **ingest:** replace card-swipe review with waveform clipping editor ([#3](https://github.com/wpfleger96/MeowDB/issues/3)) ([180f211](https://github.com/wpfleger96/MeowDB/commit/180f21169ffa675c18f18516af6020c4942a9866))
* migrate deployment from Fly.io to Proxmox homelab ([#36](https://github.com/wpfleger96/MeowDB/issues/36)) ([e747325](https://github.com/wpfleger96/MeowDB/commit/e74732599d2b6134f88b5036d1eb04ee281f3b2b))
* overhaul meow auto-detection with adaptive threshold and 3-test classifier ([#11](https://github.com/wpfleger96/MeowDB/issues/11)) ([97a8ff4](https://github.com/wpfleger96/MeowDB/commit/97a8ff4436ba084da542b99102fe1a4c028aef3c))
* photo optimization, smart Cache-Control headers, startup migration ([#25](https://github.com/wpfleger96/MeowDB/issues/25)) ([cb106fd](https://github.com/wpfleger96/MeowDB/commit/cb106fd5bd521c50817cbb918143135c5de84639))
* **photos:** add photo management view and fix silent upload failure ([#14](https://github.com/wpfleger96/MeowDB/issues/14)) ([bd03e8f](https://github.com/wpfleger96/MeowDB/commit/bd03e8f687aa160ad9219fac74031deda09e2f5b))
* **photos:** rotate, flip, crop editing + fix EXIF orientation on upload ([#29](https://github.com/wpfleger96/MeowDB/issues/29)) ([f074aca](https://github.com/wpfleger96/MeowDB/commit/f074acac2086873db6e3976ffd8750f0b38ebdb5))
* **pwa:** add PWA installability with icons and no-op service worker ([#33](https://github.com/wpfleger96/MeowDB/issues/33)) ([0560c25](https://github.com/wpfleger96/MeowDB/commit/0560c25d391b99234f98b6349718d8d64a25d111))
* **ui:** add first-class desktop layout alongside mobile and PWA ([#6](https://github.com/wpfleger96/MeowDB/issues/6)) ([5f9c32d](https://github.com/wpfleger96/MeowDB/commit/5f9c32d976aebae09304584f3b2ea271904398a6))
* **ui:** add multiselect to audio and photo file pickers ([#20](https://github.com/wpfleger96/MeowDB/issues/20)) ([f16fa3f](https://github.com/wpfleger96/MeowDB/commit/f16fa3fc9f063d091b05ab8d7cb2ea3c9641df2c))


### Bug Fixes

* add missing name field to fly.toml health check ([99e6a6e](https://github.com/wpfleger96/MeowDB/commit/99e6a6e16d9e47d7eec1839ef7478cf49dc21ade))
* bump SW cache to v2, add photos.js, switch to network-first ([#16](https://github.com/wpfleger96/MeowDB/issues/16)) ([2b66fc9](https://github.com/wpfleger96/MeowDB/commit/2b66fc922f3efb64e7e95578cc936e0d90ecfde4))
* bump SW cache to v3 to force client refresh after Cloudflare edge cache miss ([#19](https://github.com/wpfleger96/MeowDB/issues/19)) ([d145193](https://github.com/wpfleger96/MeowDB/commit/d1451936ce7667dcaf79fcd5015a4cdf6f5f85f2))
* correct e2e CI target from `just e2e` to `just test-e2e` ([#8](https://github.com/wpfleger96/MeowDB/issues/8)) ([55b01c6](https://github.com/wpfleger96/MeowDB/commit/55b01c64be4b48bb0e5be18794911a7364b4e445))
* correct e2e CI target from just e2e to just test-e2e ([55b01c6](https://github.com/wpfleger96/MeowDB/commit/55b01c64be4b48bb0e5be18794911a7364b4e445))
* **deploy:** replace archived containrrr/watchtower with maintained fork ([#40](https://github.com/wpfleger96/MeowDB/issues/40)) ([2856f71](https://github.com/wpfleger96/MeowDB/commit/2856f71cfdb453c4b48a63b8745fa647bbf2dbbb))
* downgrade Python 3.14 to 3.13 and fix except clause syntax ([#35](https://github.com/wpfleger96/MeowDB/issues/35)) ([919a7b0](https://github.com/wpfleger96/MeowDB/commit/919a7b06b49303e9abd27cb2935cc70d14211860))
* enable audio selection in iOS upload file picker ([#32](https://github.com/wpfleger96/MeowDB/issues/32)) ([1150ed6](https://github.com/wpfleger96/MeowDB/commit/1150ed66506a1a9679c397313699d9504f4b18a9))
* **fly:** revert memory to 512mb — OOM at 256mb ([#26](https://github.com/wpfleger96/MeowDB/issues/26)) ([c78c0a0](https://github.com/wpfleger96/MeowDB/commit/c78c0a0d2f4f1bf7928efa3515f268dbc7edfc91))
* include static files in installed package ([c796096](https://github.com/wpfleger96/MeowDB/commit/c796096aea2409b0826a0e544e82c0db4b79efdd))
* **photos:** bust edge cache after edits via server-side ?v= param ([#34](https://github.com/wpfleger96/MeowDB/issues/34)) ([45e1b25](https://github.com/wpfleger96/MeowDB/commit/45e1b25a629573652f57809bb37f3422436a94e0))
* **play:** eliminate CLS by deferring empty-state until count is known ([#39](https://github.com/wpfleger96/MeowDB/issues/39)) ([cf2f070](https://github.com/wpfleger96/MeowDB/commit/cf2f070af172a38bfbeeafb440be85e558045758))
* remove invalid --system flag from uv sync in Dockerfile ([560bed0](https://github.com/wpfleger96/MeowDB/commit/560bed041f9d473f708683255078ccd542a6b4b0))
* restore waveform rendering and fix SQLite thread-safety crash ([#22](https://github.com/wpfleger96/MeowDB/issues/22)) ([d64e7a0](https://github.com/wpfleger96/MeowDB/commit/d64e7a0e24b039fd28387b9d5d9837f961bfc0da))
* set Cache-Control: no-cache on static file responses ([#15](https://github.com/wpfleger96/MeowDB/issues/15)) ([1068966](https://github.com/wpfleger96/MeowDB/commit/1068966f75bf037d599ea124c3aefc0499b91ee2))
* simplify auth UX — remove AUTH_DISABLED, gate write UI on auth state ([0b460ab](https://github.com/wpfleger96/MeowDB/commit/0b460ab77196c3159e0b7959d69e9dbd8d554268))
* **ui:** mobile auth control placement + systemic Alpine $root scope bug ([#27](https://github.com/wpfleger96/MeowDB/issues/27)) ([e490046](https://github.com/wpfleger96/MeowDB/commit/e49004618156363c2db77ba35e3d6edad8cce61c))
* **ui:** resolve WaveSurfer editor not rendering after audio upload ([#30](https://github.com/wpfleger96/MeowDB/issues/30)) ([752ae5b](https://github.com/wpfleger96/MeowDB/commit/752ae5bd7dcefc80350de8347a5d31676f309a00))
* **ui:** show meow ID/date on play page, animate detail waveform, drop ID ellipsis ([#23](https://github.com/wpfleger96/MeowDB/issues/23)) ([005fc18](https://github.com/wpfleger96/MeowDB/commit/005fc181cd908994aea3c0f6c816472d6b987bcd))
* use correct flyctl-actions tag (1.5 not v1.5) ([88f222d](https://github.com/wpfleger96/MeowDB/commit/88f222d24ebf597e21617307fe35bec9dd907fed))


### Chores

* bump action versions in fly-deploy.yml ([#17](https://github.com/wpfleger96/MeowDB/issues/17)) ([c9680a0](https://github.com/wpfleger96/MeowDB/commit/c9680a0ae838c53350da1395324ef3563cde1a15))
* commit fly launch artifacts ([e12e952](https://github.com/wpfleger96/MeowDB/commit/e12e952faefb4a466cddb9662b151dd954ff497e))
* **deps:** Lock file maintenance ([#45](https://github.com/wpfleger96/MeowDB/issues/45)) ([9e2998c](https://github.com/wpfleger96/MeowDB/commit/9e2998c9fd36a5b0e365f50a76f19489fb88c73e))
* **deps:** Update all non-major dependencies ([#43](https://github.com/wpfleger96/MeowDB/issues/43)) ([da51600](https://github.com/wpfleger96/MeowDB/commit/da516009f3ed52bc5923170366db7ccbe3e718f1))
* **deps:** Update github-actions (major) ([#44](https://github.com/wpfleger96/MeowDB/issues/44)) ([532b95d](https://github.com/wpfleger96/MeowDB/commit/532b95dc09b99c8be19310b0ef46b5939590a5b8))
* move Fly.io deployment region from sjc to iad ([b899b35](https://github.com/wpfleger96/MeowDB/commit/b899b35b3970ab99e2741842c41575d7c2a284bc))
* move Fly.io primary region from sjc to iad ([#13](https://github.com/wpfleger96/MeowDB/issues/13)) ([b899b35](https://github.com/wpfleger96/MeowDB/commit/b899b35b3970ab99e2741842c41575d7c2a284bc))
* remove fly.toml and fix migration script after Fly.io teardown ([#38](https://github.com/wpfleger96/MeowDB/issues/38)) ([98b9336](https://github.com/wpfleger96/MeowDB/commit/98b93360b7117c7a4fd0d327a6d6276a4fd7d645))
* sync Justfile ([25e97e8](https://github.com/wpfleger96/MeowDB/commit/25e97e8b41f2ae25d77fa34591f261b973b6004e))
* sync Justfile ([ad3a8f8](https://github.com/wpfleger96/MeowDB/commit/ad3a8f881062bdc47bd3a579d4e787d90c9a7874))
* sync Justfile ([63910ad](https://github.com/wpfleger96/MeowDB/commit/63910ad0b2803f66400a0d7dacb6638e11b18363))
* sync pre-commit hook ([97f7cbb](https://github.com/wpfleger96/MeowDB/commit/97f7cbb95f2e9f66d2c258034ae3e1cb243f36d2))
* sync pre-commit hook ([545f270](https://github.com/wpfleger96/MeowDB/commit/545f2703daee0299fb28e3b3fb8701c92d392863))
* sync pre-commit hook ([4f941aa](https://github.com/wpfleger96/MeowDB/commit/4f941aa45eebf200bb9bb0ba3832cedd111bf747))
* sync pre-commit hook ([8041890](https://github.com/wpfleger96/MeowDB/commit/8041890c45fd372679d1b5cadd8ab948ee63bf05))
* sync pre-commit hook ([ae5f76a](https://github.com/wpfleger96/MeowDB/commit/ae5f76aecf2895494e78052b8f88cb9e1fc33021))
* update gitignore ([fbf7a4b](https://github.com/wpfleger96/MeowDB/commit/fbf7a4bb107edbd1769fb50c9ea154b923ebff28))
* update README badges ([219ed8f](https://github.com/wpfleger96/MeowDB/commit/219ed8f9168950e2baef9eb64fbb80d76e8849c3))


### Continuous Integration

* gate docker deploy on release, add release-please manifest ([#41](https://github.com/wpfleger96/MeowDB/issues/41)) ([b44dfd2](https://github.com/wpfleger96/MeowDB/commit/b44dfd2c5b386cef4c672c45814159a137011f38))
* sync CI workflow ([a006f89](https://github.com/wpfleger96/MeowDB/commit/a006f899b750c32521584fe9e582932d6fb8c02c))
* sync CI workflow ([2616e18](https://github.com/wpfleger96/MeowDB/commit/2616e182aa4f4867fe23ec10e37859893b1aaba7))
* sync release workflow ([233c01a](https://github.com/wpfleger96/MeowDB/commit/233c01aef45e227d486b75e0ec8121427a4ed542))
* sync shared files ([472d140](https://github.com/wpfleger96/MeowDB/commit/472d14079ad779b17c8c2d0992495d31c778bb5e))


### Documentation

* add ci command, single-file test example, and three gotchas to AGENTS.md ([094ff21](https://github.com/wpfleger96/MeowDB/commit/094ff2181cc22f03efab3144e207c7dd7eb53c7e))
* add recipe descriptions to Justfile ([a520bb9](https://github.com/wpfleger96/MeowDB/commit/a520bb9cd154e8f369bdb0297b28261c7203377d))
* improve Justfile recipe descriptions for clarity ([b24d06d](https://github.com/wpfleger96/MeowDB/commit/b24d06de8d8462fed4a971e32040de31a2d40507))
* update README for Proxmox migration ([#37](https://github.com/wpfleger96/MeowDB/issues/37)) ([695c448](https://github.com/wpfleger96/MeowDB/commit/695c4487cc22d2205bc5dba0438d90d56a2d4087))
* write README with architecture, local dev, and deployment guide ([14935fd](https://github.com/wpfleger96/MeowDB/commit/14935fd4f8462559514478ebcb0df0480dcf4c31))


### Refactoring

* remove service worker, add content-hashed static assets ([#24](https://github.com/wpfleger96/MeowDB/issues/24)) ([aa3c10e](https://github.com/wpfleger96/MeowDB/commit/aa3c10e6e98b018a36eaa2cd7c7141563e314a67))
