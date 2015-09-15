#-*- coding: utf-8 -*-

"""
 (c) 2014 - Copyright Red Hat Inc

 Authors:
   Pierre-Yves Chibon <pingou@pingoured.fr>

License: GPLv3 or any later version.
"""

import argparse
import ConfigParser
import datetime
import glob
import logging
import os
import rpm
import subprocess
import shutil
import time
import warnings
import re
from datetime import date

from copr.client import CoprClient

try:
    import pygit2
except ImportError:
    pass
try:
    import hglib
except ImportError:
    pass


DEFAULT_CONFIG = os.path.expanduser('~/.config/dgroc')
COPR_URL = 'http://copr.fedoraproject.org/'
# Initial simple logging stuff
logging.basicConfig(format='%(message)s')
LOG = logging.getLogger("dgroc")


class DgrocException(Exception):
    ''' Exception specific to dgroc so that we will catch, we won't catch
    other.
    '''
    pass


class GitReader(object):
    '''Defualt version control system to use: git'''
    short = 'git'

    @classmethod
    def init(cls):
        '''Import the stuff git needs again and let it raise an exception now'''
        import pygit2

    @classmethod
    def clone(cls, url, folder):
        '''Clone the repository'''
        pygit2.clone_repository(url, folder)

    @classmethod
    def pull(cls):
        '''Pull from the repository'''
        return subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def commit_hash(cls, folder):
        '''Get the latest commit hash'''
        repo = pygit2.Repository(folder)
        commit = repo[repo.head.target]
        return commit.oid.hex[:8]

    @classmethod
    def archive_cmd(cls, project, archive_name):
        '''Command to generate the archive'''
        return "git archive --format=tar --prefix=%s/ -o%s/%s HEAD" % (project,
            get_rpm_sourcedir(), archive_name)

class MercurialReader(object):
    '''Alternative version control system to use: hg'''
    short = 'hg'

    @classmethod
    def init(cls):
        '''Import the stuff Mercurial needs again and let it raise an exception now'''
        import hglib

    @classmethod
    def clone(cls, url, folder):
        '''Clone the repository'''
        hglib.clone(url, folder)

    @classmethod
    def pull(cls):
        '''Pull from the repository'''
        return subprocess.Popen(["hg", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def commit_hash(cls, folder):
        '''Get the latest commit hash'''
        repo = hglib.open(folder)
        commit = commit = repo.log('tip')[0]
        return commit.node[:12]

    @classmethod
    def archive_cmd(cls, project, archive_name):
        '''Command to generate the archive'''
        return "hg archive --type=tar --prefix=%s/ %s/%s" % (project,
            get_rpm_sourcedir(), archive_name)


def _get_copr_client():
    ''' Return the CoprClient instance.
    '''
    LOG.debug('Reading configuration for copr')
    ## Copr config check
    copr_config_file = os.path.expanduser('~/.config/copr')
    if not os.path.exists(copr_config_file):
        raise DgrocException('No `~/.config/copr` file found.')

    try:
        copr_client = CoprClient.create_from_file_config()
    except Exception as e:
        raise DgrocException(
             'Failed to read data from the copr '
             'configuration file.\n %s' % str(e))


    return copr_client


def get_arguments():
    ''' Set the command line parser and retrieve the arguments provided
    by the command line.
    '''
    parser = argparse.ArgumentParser(
        description='Daily Git Rebuild On Copr')
    parser.add_argument(
        '--config', dest='config', default=DEFAULT_CONFIG,
        help='Configuration file to use for dgroc.')
    parser.add_argument(
        '--debug', dest='debug', action='store_true',
        default=False,
        help='Expand the level of data returned')
    parser.add_argument(
        '--srpm-only', dest='srpmonly', action='store_true',
        default=False,
        help='Generate the new source rpm but do not build on copr')
    parser.add_argument(
        '--no-monitoring', dest='monitoring', action='store_false',
        default=True,
        help='Upload the srpm to copr and exit (do not monitor the build)')

    return parser.parse_args()


def update_spec(spec_file, commit_hash, archive_name, packager, email, reader):
    ''' Update the release tag and changelog of the specified spec file
    to work with the specified commit_hash.
    '''
    LOG.debug('Update spec file: %s', spec_file)
    release = '%s%s%s' % (date.today().strftime('%Y%m%d'), reader.short, commit_hash)
    output = []
    version = None
    rpm.spec(spec_file)
    with open(spec_file) as stream:
        for row in stream:
            row = row.rstrip()
            if row.startswith('Version:'):
                version = row.split('Version:')[1].strip()
            if row.startswith('Release:'):
                if commit_hash in row:
                    raise DgrocException('Spec already up to date')
                LOG.debug('Release line before: %s', row)
                rel_num = row.split('ase:')[1].strip().split('%{?dist')[0]
                rel_list = rel_num.split('.')
                if reader.short in rel_list[-1]:
                    rel_list = rel_list[:-1]
                if rel_list[-1].isdigit():
                    rel_list[-1] = str(int(rel_list[-1])+1)
                rel_num = '.'.join(rel_list)
                LOG.debug('Release number: %s', rel_num)
                row = 'Release:        %s.%s%%{?dist}' % (rel_num, release)
                LOG.debug('Release line after: %s', row)
            if row.startswith('Source0:'):
                row = 'Source0:        %s' % (archive_name)
                LOG.debug('Source0 line after: %s', row)
            if row.startswith('%changelog'):
                output.append(row)
                output.append(rpm.expandMacro('* %s %s <%s> - %s-%s.%s' % (
                    date.today().strftime('%a %b %d %Y'), packager, email,
                    version, rel_num, release)
                ))
                output.append('- Update to %s: %s' % (reader.short, commit_hash))
                row = ''
            output.append(row)

    with open(spec_file, 'w') as stream:
        for row in output:
            stream.write(row + '\n')

    LOG.info('Spec file updated: %s', spec_file)


def get_rpm_sourcedir():
    ''' Retrieve the _sourcedir for rpm
    '''
    dirname = subprocess.Popen(
        ['rpm', '-E', '%_sourcedir'],
        stdout=subprocess.PIPE
    ).stdout.read()[:-1]
    return dirname


def _get_archive_name(out, project):
    ''' Try to find generated archive name in the archive_cmd output
    '''
    name = ''
    for line in out:
        search = re.search(r"" + project + r"\-[^\s]*\.tar(\.gz|\.bz2)", line)
        if search:
            name = search.group()

    if name:
        LOG.debug('Archive name from output: %s' % name)
        return name

    if out:
        LOG.debug('Last line of archive_cmd output: \"%s\"' % line)

    raise DgrocException('No archive name found.')


def generate_archive(config, project, git_folder, commit_hash, reader):
    ''' For a given project in the configuration file generate a new source
    archive if it is possible.
    '''

    if config.has_option(project, 'archive_cmd'):
        archive_name = ''
        cmd = config.get(project, 'archive_cmd')
    else:
        archive_name = "%s-%s.tar" % (project, commit_hash)
        cmd = reader.archive_cmd(project, archive_name)

    LOG.debug('Command to generate archive: %s' % cmd)

    cwd = os.getcwd()
    os.chdir(git_folder)
    pull = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True)
    out = pull.communicate()

    # no archive name -> need to read it from output and move the archive
    # to rpm source dir
    if not archive_name:
        archive_name = _get_archive_name(out, project)
        if not os.path.isfile(git_folder + "/" + archive_name):
            LOG.info('Got archive name %s, but no such file found ' \
                     'in %s' % (archive_name, git_folder))
            raise DgrocException('No archive to generate SRPM.')
        shutil.move(git_folder + '/' + archive_name,
                    get_rpm_sourcedir() + '/' + archive_name)

    os.chdir(cwd)

    return archive_name


def generate_new_srpm(config, project, first=True):
    ''' For a given project in the configuration file generate a new srpm
    if it is possible.
    '''
    if not config.has_option(project, 'scm') or config.get(project, 'scm') == 'git':
        reader = GitReader
    elif config.get(project, 'scm') == 'hg':
        reader = MercurialReader
    else:
        raise DgrocException(
            'Project "%s" tries to use unknown "scm" option'
            % project)
    reader.init()
    LOG.debug('Generating new source rpm for project: %s', project)
    if not config.has_option(project, '%s_folder' % reader.short):
        raise DgrocException(
            'Project "%s" does not specify a "%s_folder" option'
            % (project, reader.short))

    if not config.has_option(project, '%s_url' % reader.short) and not os.path.exists(
            config.get(project, '%s_folder' % reader.short)):
        raise DgrocException(
            'Project "%s" does not specify a "%s_url" option and its '
            '"%s_folder" option does not exists' % (project, reader.short, reader.short))

    if not config.has_option(project, 'spec_file'):
        raise DgrocException(
            'Project "%s" does not specify a "spec_file" option'
            % project)

    # git clone if needed
    git_folder = config.get(project, '%s_folder' % reader.short)
    if '~' in git_folder:
        git_folder = os.path.expanduser(git_folder)

    if not os.path.exists(git_folder):
        git_url = config.get(project, '%s_url' % reader.short)
        LOG.info('Cloning %s', git_url)
        reader.clone(git_url, git_folder)

    # git pull
    cwd = os.getcwd()
    os.chdir(git_folder)
    pull = reader.pull()
    out = pull.communicate()
    os.chdir(cwd)
    if pull.returncode:
        LOG.info('Strange result of the %s pull:\n%s', reader.short, out[0])
        if first:
            LOG.info('Gonna try to re-clone the project')
            shutil.rmtree(git_folder)
            generate_new_srpm(config, project, first=False)
        return

    # Retrieve last commit
    commit_hash = reader.commit_hash(git_folder)
    LOG.info('Last commit: %s', commit_hash)

    # Check if commit changed
    changed = False
    if not config.has_option(project, '%s_hash' % reader.short):
        config.set(project, '%s_hash  % reader.short', commit_hash)
        changed = True
    elif config.get(project, '%s_hash' % reader.short) == commit_hash:
        changed = False
    elif config.get(project, '%s_hash  % reader.short') != commit_hash:
        changed = True

    if not changed:
        return

    # Build sources
    archive_name = generate_archive(config, project, git_folder, commit_hash, reader)

    # Update spec file
    spec_file = config.get(project, 'spec_file')
    if '~' in spec_file:
        spec_file = os.path.expanduser(spec_file)

    update_spec(
        spec_file,
        commit_hash,
        archive_name,
        config.get('main', 'username'),
        config.get('main', 'email'),
        reader)

    # Copy patches
    if config.has_option(project, 'patch_files'):
        LOG.info('Copying patches')
        candidates = config.get(project, 'patch_files').split(',')
        candidates = [candidate.strip() for candidate in candidates]
        for candidate in candidates:
            LOG.debug('Expanding path: %s', candidate)
            candidate = os.path.expanduser(candidate)
            patches = glob.glob(candidate)
            if not patches:
                LOG.info('Could not expand path: `%s`', candidate)
            for patch in patches:
                filename = os.path.basename(patch)
                dest = os.path.join(get_rpm_sourcedir(), filename)
                LOG.debug('Copying from %s, to %s', patch, dest)
                shutil.copy(
                    patch,
                    dest
                )

    # Generate SRPM
    env = os.environ
    env['LANG'] = 'C'
    build = subprocess.Popen(
        ["rpmbuild", "-bs", spec_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env)
    out = build.communicate()
    os.chdir(cwd)
    if build.returncode:
        LOG.info(
            'Strange result of the rpmbuild -bs:\n  stdout:%s\n  stderr:%s',
            out[0],
            out[1]
        )
        return
    srpm = out[0].split('Wrote:')[1].strip()
    LOG.info('SRPM built: %s', srpm)

    return srpm


def copr_build(config, srpms):
    ''' Using the information provided in the configuration file,
    run the build in copr.
    '''

    ## dgroc config check
    if not config.has_option('main', 'copr_url'):
        warnings.warn(
            'No `copr_url` option set in the `main` section of the dgroc '
            'configuration file, using default: %s' % COPR_URL)
        copr_url = COPR_URL
    else:
        copr_url = config.get('main', 'copr_url')

    if not copr_url.endswith('/'):
        copr_url = '%s/' % copr_url

    copr_client = _get_copr_client()

    builds_list = []
    ## Build project/srpm in copr
    for project in srpms:
        if config.has_option(project, 'copr'):
            copr = config.get(project, 'copr')
        else:
            copr = project

        try:
            res = copr_client.create_new_build(copr, pkgs=[srpms[project]])

            builds_list += res.builds_list

        except Exception as e:
            LOG.info("Something went wrong:\n  %s", str(e))
    return builds_list


def check_copr_build(config, builds_list):
    ''' Check the status of builds running in copr.
    '''

    unfinished = []
    ## Build project/srpm in copr
    for build in builds_list:
        status = build.handle.get_build_details().status
        LOG.info('  Build %s: %s', build.build_id, status)

        if status not in ('skipped', 'failed', 'succeeded'):
            unfinished.append(build)
    return unfinished


def main():
    '''
    '''
    # Retrieve arguments
    args = get_arguments()

    global LOG
    #global LOG
    if args.debug:
        LOG.setLevel(logging.DEBUG)
    else:
        LOG.setLevel(logging.INFO)

    # Read configuration file
    config = ConfigParser.ConfigParser()
    config.read(args.config)

    if not config.has_option('main', 'username'):
        raise DgrocException(
            'No `username` specified in the `main` section of the '
            'configuration file.')

    if not config.has_option('main', 'email'):
        raise DgrocException(
            'No `email` specified in the `main` section of the '
            'configuration file.')

    srpms = {}
    for project in config.sections():
        if project == 'main':
            continue
        LOG.info('Processing project: %s', project)
        try:
            srpm = generate_new_srpm(config, project)
            if srpm:
                srpms[project] = srpm
        except DgrocException, err:
            LOG.info('%s: %s', project, err)

    LOG.info('%s srpms generated', len(srpms))
    if not srpms:
        return

    if args.srpmonly:
        return

    try:
        build_ids = copr_build(config, srpms)
    except DgrocException, err:
        LOG.info(err)

    if args.monitoring:
        LOG.info('Monitoring %s builds...', len(build_ids))
        while build_ids:
            time.sleep(45)
            LOG.info(datetime.datetime.now())
            build_ids = check_copr_build(config, build_ids)


if __name__ == '__main__':
    main()
