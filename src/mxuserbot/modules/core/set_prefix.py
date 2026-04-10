from typing import Any
from mautrix.types import MessageEvent
from ...core import loader

@loader.tds
class MatrixModule(loader.Module):
    strings = {
        "name": "PrefixModule",
        "_cls_doc": "Управление префиксом",
        "allowed_symbols": "!\"./\\,;:@#$%^&*-_+=?|~",
        "error_no_args": "<b>Ошибка:</b> вы не указали префикс.\nПример: <code>.set_prefix !</code>",
        "error_too_long": "<b>Ошибка:</b> префикс должен состоять только из <b>одного</b> символа.",
        "error_set_prefix": "<b>Ошибка:</b> символ <code>{new_prefix}</code> запрещен.\n"
                            "Можно использовать только: <code>{allowed_symbols}</code>",
        "success_set_prefix": "✅ Префикс успешно изменен на: <code>{new_prefix}</code>"
    }

    @loader.command()
    async def set_prefix(self, mx: Any, event: MessageEvent):
        """Установить новый префикс (только спец. символы)"""
        
        body = getattr(event.content, "body", "")
        parts = body.split()
        
        if len(parts) < 2:
            return await mx.answer(self.strings.get("error_no_args"))

        new_prefix = parts[1]

        if len(new_prefix) != 1:
            return await mx.answer(self.strings.get("error_too_long"))

        allowed = self.strings.get("allowed_symbols")
        if new_prefix not in allowed:
            return await mx.answer(
                self.strings.get("error_set_prefix").format(
                    new_prefix=new_prefix,
                    allowed_symbols=allowed
                )
            )

        query = [new_prefix]
        await self._set("prefix", query)
        
        if hasattr(mx, "prefixes"):
            mx.prefixes = query

        await mx.answer(
            self.strings.get("success_set_prefix").format(new_prefix=new_prefix)
        )