from setuptools import setup

setup(name='remind',
      version='0.1.0',
      description='''
       Remind Python lib
       ''',
      author='Jochen Sprickerhof',
      author_email='remind@jochen.sprickerhof.de',
      license='GPLv3+',
      url='https://github.com/jspricke/python-remind',
      keywords=['Remind'],
      classifiers=['Programming Language :: Python'],

      setup_requires=['nose>=1.3', 'coverage'],
      install_requires=['python-dateutil', 'vobject'],
      py_modules=['remind', 'ics_compare'],

      entry_points={
          'console_scripts': [
              'rem2ics = remind:rem2ics',
              'ics2rem = remind:ics2rem',
              'icscomp = ics_compare:main',
              ]
          },

      test_suite='nose.collector',
     )
