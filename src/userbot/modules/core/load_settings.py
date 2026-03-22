from loguru import logger
from ...registry import active_modules

def load_settings(data):
    if not data:
        return
    if not data.get('module_settings'):
        return
    for modulename, moduleobject in active_modules.items():
        if data['module_settings'].get(modulename):
            try:
                moduleobject.set_settings(
                    data['module_settings'][modulename])
            except Exception:
                logger.exception(f'unhandled exception {modulename}.set_settings')