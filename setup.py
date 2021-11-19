import setuptools


with open("readme.md", "r") as f:
    long_description = f.read()


setuptools.setup(
    name="ddkypy",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="http://github.com/kyle-verhoog/datadog-python",
    packages=setuptools.find_packages(),
    install_requires=[
        "ddtrace",
        "requests",
    ],
    python_requires=">=2.7",
)
