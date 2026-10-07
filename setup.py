from setuptools import setup, find_packages

setup(
    name="isycode",
    packages=find_packages(where="src", include=["isycode*"]),
    package_dir={"": "src"},
    package_data={
        "isycode": [
            "isycode.tcss",
            "assets/*",
            "bundled_skills/**/*",
        ],
    },
    include_package_data=True,
)
