dgroc
=====

:Author: Pierre-Yves Chibon <pingou@pingoured.fr>


dgroc: Daily Git Rebuild On Copr

This project aims at easily provide daily build of a project tracked via
git and made available via `copr <http://copr.fedoraproject.org>`_.


.. contents::


Get it running
==============

* Retrieve the sources::

    git clone https://github.com/pypingou/dgroc.git


* Create the configuration file ``~/.config/dgroc``

* Fill the configuration file, for example::

    [main]
    username = me
    email = my_email@example.com
    copr_url = https://copr.fedoraproject.org/

    [subsurface]
    git_url = git://subsurface.hohndel.org/subsurface.git
    git_folder = /tmp/subsurface/
    spec_file = ~/GIT/subsurface/subsurface.spec

    [guake]
    copr = subsurface
    git_url = https://github.com/Guake/guake.git
    git_folder = /tmp/guake/
    spec_file = ~/GIT/guake/guake.spec
    patch_files = ~/GIT/guake/guake-0.2.2-fix_vte.patch,
                  ~/GIT/guake/0001-Remove-vte-check-in-the-configure.ac.patch


The Main section
----------------
`username`` The name to use in the changelog of the spec file when updating
it.

``email`` The email to use in the changelog of the spec file when updating
it.

``copr_url`` The url of `copr`_ to use.


The project section
-------------------

For each project, only three options are required:

``git_url`` The url to the git repository, that is only required if the git
repo is not already cloned on the disk (see ``git_folder``).

``git_folder`` The location of the local clone of the git repository to
build.

``spec_file`` The location of the spec file for the project to build.

``patch_files`` A comma separated list of patches required to build the
project.
These files will be copied over to the rpm sourcedir to be present when
building the source rpm.

``copr`` The optional name of the copr repository to build the package within.
When not set, the project name (from `[]`) is used.

``archive_cmd`` Alternative command to generate source archive. This command
needs to print the name of the generated archive to stdout.

.. Note:: The spec file should be fully functionnal as all ``dgroc`` will do is
          update the ``Source0``, ``Release`` and add an entry in the ``Changelog``.

.. Note:: You might have to set in your spec file the %setup line to::

              %setup -q -n <projectname>


Run the project
---------------

From the sources, it requires few steps:

* Install dependencies::

    dnf install libgit2-devel python-virtualenvwrapper python-copr

* Create a virtual env::

    mkvirtualenv dgroc

* Install the python dependencies::

    pip install -r requirements.txt

* Run dgroc::

    ./dgroc.py

For more information/output run ``./dgroc.py --debug``


Run dgroc daily
---------------

The easiest way to run dgroc daily is to simply rely on `cron
<https://en.wikipedia.org/wiki/Cron>`_

Here is an example cron entry that you will need to adjust for your setup::

    30 10 * * * python /home/pingou/dgroc/dgroc.py


This cron will run every day at 10:30 am and call the dgroc.py script within the
dgroc clone
