import glob
import importlib.util
from os.path import basename, dirname, join

from config import CORE_RUNTIME

modules = glob.glob(join(dirname(__file__), "*.py"))
SINGBOX_SKIP_MODULES = {
    "0_xray_core",
    "record_usages",
    "reset_user_data_usage",
    "review_users",
}

for file in modules:
    name = basename(file).replace('.py', '')
    if name.startswith('_'):
        continue
    if CORE_RUNTIME == "singbox" and name in SINGBOX_SKIP_MODULES:
        continue

    spec = importlib.util.spec_from_file_location(name, file)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
