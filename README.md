# MxUserbot

<img width="1376" height="768" alt="result" src="https://github.com/user-attachments/assets/2e266925-c17b-49db-ac7b-1635cb3799b8" />

**What is a userbot:** A bot that runs directly on your account, acting on your behalf.  
**Purpose:** From showing off to your friends that you use bot commands from your account to automation and useful modules. It all depends on you.

**SPACE:** [Matrix Space](https://matrix.to/#/#SpacePashaHatsune:matrix.org)

> [!CAUTION]
> **BETA**  
> The project is in the beta stage. ShitCode. Don't judge too harshly :)

---

## Contribution

We accept **[Issues](https://github.com/MxUserBot/issues/issues)** and **[Pull requests](https://github.com/MxUserBot/MxUserbot/pulls)**.  
If you have ideas or code — send them over, I will review everything.

---

## Advantages

* Rewritten in `mautrix-python`
* Support for [`uv`](https://docs.astral.sh/uv/#highlights)
* Simple module creation
* Modular structure
* Module security
* E2EE / SAS out of the box

---

## Installation

### Docker
```bash
git clone https://github.com/PashaHatsune/MxUserbot.git
cd MxUserbot

docker build -t mxuserbot .
docker run -it mxuserbot
```

### Manual Installation
```bash
git clone https://github.com/PashaHatsune/MxUserbot.git
cd MxUserbot

# Sync and run
uv sync
uv run -m src.mxuserbot
```

---

## Documentation

Quick links:

- [Module Development](docs/module-development.md)
- [Utils Reference](docs/utils-reference.md)
- [Security](docs/security.md)

---

# Donate
https://destream.net/live/Pashahatsune/donate


This software is provided **"as is"**, without warranty of any kind, express or implied. By using this userbot, you acknowledge that:

* **Full Responsibility:** You are solely responsible for your actions and any consequences resulting from the use of this software.
* **No Liability:** The developer shall not be held liable for any damages, including but not limited to account bans, data loss, or legal issues.
* **Strict Prohibition:** Use of this bot for fraudulent activities, spam, or any actions that violate terms of service or local laws is strictly prohibited.