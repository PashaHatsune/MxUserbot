LISTEN UP. Here is your dev guide. Clean, simple, and in English.

To write a module, you need:
1. An installed MxUserbot.
2. A `.py` file in `src/mxuserbot/modules/community`. Let’s call it `test.py`.

### Module Basics:

1. **Import the essentials:**
```python
from ...core import loader, utils
```

2. **Define the `Meta` class:**
```python
class Meta:
    name = "AstolfoModule"
    _cls_doc = "Sends random Astolfo pics from astolfo.rocks" 
    version = "1.1"
    tags = ["api"]
    # Optional: dependencies = ["pillow", "av"]
```
**Required:** `name`, `_cls_doc`, `version`, `tags`.
**Optional:** `dependencies` (list of pip packages).

3. **Create the main class:**
```python
@loader.tds # Always use this decorator
class TestModule(loader.Module):
    strings = {"error": "Failed to get cuteness"}

    config = {
        "limit": loader.ConfigValue(10, "Request limit", lambda x: x > 0),
        "api_key": loader.ConfigValue("NONE", "API Key"),
        "silent": loader.ConfigValue(False, "Silent mode")
    }
```

**Quick breakdown:**
* **Class naming:** The core looks for a class with "Module" in its name.
* **`strings`:** MUST be a dictionary. Use it for all your texts. Access them via `self.strings.get("key")`.
* **`config`:** Optional. Use `loader.ConfigValue(default, description, validator)`.

### Writing Commands:

```python
    @loader.command()
    async def test(self, mx, event):
        """test command to get images"""
```

* `@loader.command()`: Tells the core this is a command. You can use `@loader.command(name="miku")` to change the trigger.
* **Arguments:** 
    * `self`: The class instance.
    * `mx`: The interface (client wrapper).
    * `event`: The mautrix MessageEvent.
* **IMPORTANT:** You **MUST** write a docstring (the text in triple quotes). If a function has no docstring, the loader will ignore it.

### Using Utils:

`utils` is your best friend. It makes life easier:
* `utils.request`: Handles aiohttp requests.
* `utils.answer`: Edits your message or sends a new one. Best practice: use `self.strings.get()`.
* `utils.send_image`: Uploads and sends images. Accepts URLs or bytes.

### Full Example:

```python
from ...core import loader, utils

class Meta:
    name = "AstolfoModule"
    _cls_doc = "Sends random Astolfo pics" 
    version = "1.1"
    tags = ["api"]

@loader.tds
class TestModule(loader.Module):
    strings = {"error": "API is down, rip."}

    @loader.command()
    async def astolfo(self, mx, event):
        """Get a random Astolfo pic"""
        api_url = "https://astolfo.rocks/api/images/random"
        data = await utils.request(api_url, params={"rating": "safe"})

        if not data:
            return await utils.answer(mx, self.strings.get("error"))

        img_url = f"https://astolfo.rocks/astolfo/{data['id']}.{data['file_extension']}"
        image_bytes = await utils.request(img_url, return_type="bytes")

        await utils.send_image(mx, event, image_bytes, file_name="astolfo.jpg")
```

### Permissions (Security):
By default, commands are available to the **Owner** and everyone in the **SUDO** list.

If you want to change this, pass the `security` argument to the decorator:
* `@loader.command(security=loader.OWNER)` — Only you.
* `@loader.command(security=loader.EVERYONE)` — Anyone in the chat.
* `@loader.command()` — Default (Owner + Sudo).

---
**Note:** Check `src/mxuserbot/core/utils.py` for more methods. If you're lazy, I generated a [utils reference here](utils-reference.md) using AI. I didn't feel like writing it all out manually. Sorry.