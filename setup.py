from setuptools import find_packages, setup

setup(
    name="codex-dynamicflow",
    version="0.1.0",
    description="External workflow runner for Codex CLI",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "codex-dynamicflow=codex_dynamicflow.cli:main",
            "codex-dynamicflow-mcp=codex_dynamicflow.mcp_server:main",
        ]
    },
)
