from setuptools import setup, find_packages

setup(
    name="modelapro",
    version="0.1.0",
    description="CONFENGE MODELA PRO - Sistema de Avaliação Imobiliária com IA",
    author="CONFENGE",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "streamlit>=1.30.0",
        "fastapi>=0.109.0",
        "uvicorn>=0.27.0",
        "pandas>=2.2.0",
        "numpy>=1.26.0",
        "scipy>=1.12.0",
        "statsmodels>=0.14.1",
        "matplotlib>=3.8.2",
        "seaborn>=0.13.1",
        "redis>=5.0.1",
        "python-multipart>=0.0.6",
        "jinja2>=3.1.3",
        "weasyprint>=60.2",
        "python-dotenv>=1.0.0",
        "websockets>=12.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
            "black>=24.1.0",
            "flake8>=7.0.0",
            "mypy>=1.8.0",
            "httpx>=0.26.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "modelapro=frontend.app:main",
            "modelapro-api=backend.api:main",
        ]
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Financial and Insurance Industry",
        "Programming Language :: Python :: 3.11",
    ],
)
