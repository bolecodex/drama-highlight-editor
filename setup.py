from setuptools import find_packages, setup

setup(
    name="drama-highlight-cut",
    version="0.1.0",
    description="短剧投流高光分析与 FFmpeg 成片生产 CLI",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={"drama_cut": ["templates/*.txt", "templates/index.json"]},
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=[
        "httpx>=0.25",
        "openai>=1.0",
        "pydantic>=2.0",
        "python-dotenv>=1.0",
        "typer>=0.12",
    ],
    entry_points={"console_scripts": ["drama-cut=drama_cut.cli:app"]},
)
