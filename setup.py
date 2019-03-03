from setuptools import setup, find_packages

setup(
    name='Flask-DebugToolbar-Django',
    version="0.1",
    description='A Django ORM panel for the Flask Debug Toolbar',
    # long_description=open('README.md').read(),
    author='Malthe Jørgensen',
    # author_email='malthe.jorgensen@gmail.com',
    # url='https://github.com/bcarlin/flask-debugtoolbar-mongo',
    license='MIT',
    packages=find_packages(exclude=('example',)),
    include_package_data=True,
    zip_safe=False,
    setup_requires=['Django>=2.1', 'Flask-DebugToolbar'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Database',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
