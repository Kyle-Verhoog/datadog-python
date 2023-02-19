import setuptools


with open("readme.md", "r") as f:
    long_description = f.read()


setuptools.setup(
    name="ddkypy",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="http://github.com/kyle-verhoog/datadog-python",
    packages=setuptools.find_packages(),
    package_data={"datadog": ["py.typed"]},
    install_requires=[
        "ddtrace==1.8.0",
        "requests",
        "GitPython",
        "typing; python_version<'3.5'",
        "typing_extensions",
    ],
    python_requires=">=2.7",
    tests_require=[
        "mypy",
        "black",
        "types-requests",
        "types-setuptools",
    ],
)
