from setuptools import find_packages, setup

setup(
    name="codex-flow",
    version="0.1.0",
    description="External workflow runner for Codex CLI",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "codex-flow=codex_flow.cli:main",
            "codex-flow-mcp=codex_flow.mcp_server:main",
        ]
    },
)
