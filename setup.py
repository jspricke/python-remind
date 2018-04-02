from setuptools import setup

setup(name='remind',
      version='0.13.0',
      description='Remind Python library',
      long_description=open('README.rst').read(),
      author='Jochen Sprickerhof',
      author_email='remind@jochen.sprickerhof.de',
      license='GPLv3+',
      url='https://github.com/jspricke/python-remind',
      keywords=['Remind'],
      classifiers=[
          'Programming Language :: Python',
          'Development Status :: 4 - Beta',
          'Environment :: Console',
          'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
          'Topic :: Office/Business :: Scheduling',
          'Topic :: Software Development :: Libraries :: Python Modules',
      ],

      setup_requires=['nose>=1.3', 'coverage'],
      install_requires=['python-dateutil', 'pytz', 'tzlocal', 'vobject'],
      py_modules=['remind', 'ics_compare'],

      entry_points={
          'console_scripts': [
              'rem2ics = remind:rem2ics',
              'ics2rem = remind:ics2rem',
              'icscomp = ics_compare:main',
          ]
      },

      test_suite='nose.collector',)
