---
<img width="1376" height="768" alt="999" src="https://github.com/user-attachments/assets/778dce44-de22-4f52-88c6-f56b3fa9d297" />

Matrix-юзербот, созданный как переосмысление проекта [Hemppa](https://github.com/vranki/hemppa).

**Что такое юзербот:** бот, который работает прямо на вашем аккаунте, действуя от вашего лица.

**SPACE:** [Matrix Space](https://matrix.to/#/#SpacePashaHatsune:matrix.org)

> **Alpha**
> Проект находится в ранней стадии. ГовноКод. Не судите строго :)

---

## Участие в разработке

Принимаются **Issue** и **Pull requests**.
Есть идеи или код — присылайте, всё рассмотрю.

---

## О чем этот форк

После перехода из Telegram не хватало привычных юзерботов.
Hemppa подошёл, но реализация «всё в одном файле» была неудобной. Решил форкнуть и переработать под модульную структуру.

**Что изменено:**

* Переписан на `mautrix-python`
* Поддержка `uv`
* Простое (почти) написание модулей
* Модульная структура
* (Плохая) безопасность
* Разделение модулей: `community` / `core`
* E2EE включено по умолчанию (можно легко выключить)

---

## Установка

```bash
git clone https://github.com/PashaHatsune/MxUserbot.git
cd MxUserbot

# Синхронизация и запуск
uv sync
uv run -m src.mxuserbot
```

---

## Как написать свой модуль

1. Создай файл в папке модулей.
2. Импортируй лоадер: `from ...core import loader`.
3. Наследуй класс `MatrixModule` от `loader.Module`.

### Пример модуля

```python
from ...core import loader

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "HelloModule",       # Имя модуля
        "_cls_doc": "выводит приветственное сообщение",  # Описание
        "Hello": "Привет всем! Это тестовый модуль!"
    }

    @loader.command()
    async def hello(self, mx, event) -> None:
        """Отправляет приветственное сообщение"""
        await mx.client.send_text(
            room_id=event.room,
            text=self.strings["Hello"]
        )
```

> **Совет:** Чтобы задать свою команду, используй `@loader.command(name="mycommand")`. Тогда вызов будет через `!mycommand`.

---