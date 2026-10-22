import enum
import json
import os


class PlanId(enum.Enum):
    NO_PLAN = 0  # for single case execution without testrail plan


class EPG_HUD_PlanId(enum.Enum):
    EU = 24529569  # EU Plan
    GLOBAL = 24529568  # Global Plan
    LATAM = 24529572  # LATAM Plan
    NA = 24529571  # NA Plan
    AU = 24529575  # AU Plan
    NO_PLAN = 0  # for single case execution without testrail plan


class LTP_PlanId(enum.Enum):
    EU = 25168259  # EU Plan
    GLOBAL = 25168234  # Global Plan
    LATAM = 25168248  # LATAM Plan
    NA = 25168244  # NA Plan
    NO_PLAN = 0  # for single case execution without testrail plan


class MyPlanId(enum.Enum):
    OPM_DE_R1 = 25475075  # OPM DE R1 Plan


ACTIVATE_ACCOUNT = {
    "US": "yuzheng@roku.com",
    "DE": "hkhaki.roku@gmail.com",
    "PA": "rokutest_pan@outlook.com",
    "UK": "",
    "CO": "",
    "BR": "brtestroku@outlook.com",
    "MX": "",
    "AU": "rtvsp_sh_eurokutest_au@roku.com",
    "CA": "catestroku@gmail.com",
}


class DeviceInfo:
    def __init__(self):
        self._devices = {}
        self.load_device_json()

    def load_device_json(self):
        device_conf_dir = os.path.join(os.path.dirname(__file__))
        for filename in os.listdir(device_conf_dir):
            if not filename.endswith(".json"):
                continue

            device_name = filename.replace(".json", "")
            activate_email = next(
                (v for k, v in ACTIVATE_ACCOUNT.items() if k in device_name.upper()), ""
            )

            with open(os.path.join(device_conf_dir, filename), "r") as f:
                self._devices[device_name] = {
                    "name": device_name,
                    "config": json.load(f),
                    "activate_email": activate_email,
                }

    @property
    def devices(self):
        return self._devices


def main():
    print(DeviceInfo().devices)


if __name__ == "__main__":
    raise SystemExit(main())
