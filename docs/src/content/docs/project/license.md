---
title: License
description: Probatio is open source under the MIT License.
---

Probatio is free and open-source software, distributed under the **MIT License**.
In short: you may use, copy, modify, and distribute it, including in commercial
and closed-source projects, as long as the copyright notice and this permission
notice are included. The software is provided "as is", without warranty.

MIT was a deliberate choice: it lets Probatio fit anywhere voluptuous did,
including Home Assistant, without trading a maintenance win for a license
headache ([ADR-002](https://github.com/frenck/probatio/blob/main/adr/002-mit-license.md)).
The clean-room reimplementation ([ADR-001](https://github.com/frenck/probatio/blob/main/adr/001-clean-room-reimplementation-of-voluptuous.md)) is what makes that
license honest: no voluptuous source is copied, so nothing constrains it.

The authoritative copy is [`LICENSE`](https://github.com/frenck/probatio/blob/main/LICENSE)
in the repository.

## MIT License

```text
MIT License

Copyright (c) 2026 Franck Nijhof

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Third-party notices

Probatio has no third-party runtime dependencies. It is pure Python and uses
only the standard library at runtime, so nothing third-party is bundled in the
wheel. The details, including the optional integrations that ship under their own
licenses when you install them yourself, are in
[`THIRD_PARTY_LICENSES.md`](https://github.com/frenck/probatio/blob/main/THIRD_PARTY_LICENSES.md)
in the repository.
