########
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import os
import logging
import subprocess
# from time import time

import retrying
from tinydb import TinyDB

# from .plugins import handler
from . import utils, constants
from .exceptions import SurchError


logger = utils.logger

# class Repo(object):
#     def __init__(self,
#                  repo_url,
#                  search_list,
#                  pager=None,
#                  verbose=False,
#                  config_file=None,
#                  results_dir=None,
#                  print_result=False,
#                  cloned_repo_dir=None,
#                  consolidate_log=False,
#                  remove_cloned_dir=False,
#                  **kwargs):
#         """Surch repo instance init

#         :param repo_url: get http / ssh repository for cloning (string)
#         :param search_list: list of string we want to search (list)
#         :param verbose: log level (boolean)
#         :param results_dir: path to result file (string)
#         :param print_result: this flag print result file in the end (boolean)
#         :param cloned_repo_dir: path for cloned repo (string)
#         :param consolidate_log:
#                        this flag decide if save the old result file (boolean)
#         :param remove_cloned_dir:
#                         this flag for removing the clone directory (boolean)
#         """

#         utils.assert_executable_exists('git')

#         logger = utils.logger
#         logger.setLevel(logging.DEBUG if verbose else logging.INFO)

#         config_file = config_file
#         print_result = print_result
#         remove_cloned_dir = remove_cloned_dir
#         repo_url = repo_url
#         organization = repo_url.rsplit('.com/', 1)[-1].rsplit('/', 1)[0]
#         repo_name = repo_url.rsplit('/', 1)[-1].rsplit('.', 1)[0]
#         cloned_repo_dir = cloned_repo_dir or os.path.join(
#             organization, constants.CLONED_REPOS_PATH)
#         repo_path = os.path.join(cloned_repo_dir, repo_name)
#         quiet_git = '--quiet' if not verbose else ''
#         verbose = verbose
#         pager = handler.plugins_handle(
#             config_file=config_file, plugins_list=pager)
#         results_dir = \
#            os.path.join(results_dir, 'results.json') if results_dir else None
#         results_file_path = results_dir or os.path.join(
#             constants.RESULTS_PATH, organization, 'results.json')
#         utils.handle_results_file(results_file_path, consolidate_log)

#         error_summary = []
#         result_count = 0


def run(command):
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True)
    proc.stdout, proc.stderr = proc.communicate()
    return proc


def _git_clone(source, destination):
    logger.info('Cloning {0} to {1}...'.format(source, destination))
    run('git clone {0} {1}'.format(source, destination))


def _git_pull(repo_path):
    logger.info('Pulling {0}...'.format(repo_path))
    run('git -C {0} pull'.format(repo_path))


def _git_get_remote(repo_path):
    command = 'git -C {0} config --get remote.origin.url'.format(repo_path)
    return subprocess.check_output(command.format(repo_path), shell=True)


def _get_repo_props(source):
    # TODO: Handle repository remote doesn't exist
    if '://' in source:
        org_name, repo_name = source.rsplit('/', 2)[1:]
        if repo_name.endswith('.git'):
            repo_name = os.path.splitext(repo_name)[0]
        local_path = os.path.join(
            constants.CLONED_REPOS_PATH, org_name, repo_name)
    elif source.startswith(':'):
        org_name, repo_name = source.lstrip(':').split('/', 1)
        source = 'https://github.com/{0}'.format(source[1:])
        local_path = os.path.join(
            constants.CLONED_REPOS_PATH, org_name, repo_name)
    elif os.path.isdir(source):
        result = run('git -C {0} rev-parse'.format(source))
        if result.returncode != 0:
            # TODO: Handle appropriately
            raise
        local_path = source
        # git@github.com:nir0s/surch.git
        # https://github.com/nir0s/surch.git
        # TODO: Instead, create a git url parser
        remote = _git_get_remote(local_path).replace(':', '/')
        org_name, repo_name = remote.rsplit('/', 2)[1:]
        if repo_name.endswith('.git'):
            repo_name = os.path.splitext(repo_name)[0]
    else:
        # TODO: Handle appropriately
        raise

    return dict(name=repo_name, org=org_name, local_path=local_path)


@retrying.retry(stop_max_attempt_number=3)
def _get_repo(source, local_path, no_sync):
    """Retrieve a repository

    If it doesn't exist, clone it. If it is, pull all of its branches

    Allow to download by:
        * Passing the full cloneable url (e.g. https://github.com/nir0s/ghost)
        * Passing a path (e.g. /my/repos/repo)
        * Passing a github-style repo (e.g. :nir0s/ghost)
    """
    # TODO: Handle repository remote doesn't exist

    if os.path.isdir(local_path):
        if not no_sync:
            _git_pull(local_path)
    else:
        _git_clone(source, local_path)
    return local_path


def _get_all_commits(repo_path):
    """Get the sha-id of the commit
    """
    logger.debug('Retrieving list of commits...')
    try:
        commits = subprocess.check_output(
            'git -C {0} rev-list --all'.format(repo_path), shell=True)
        return commits.splitlines()
    except subprocess.CalledProcessError:
        return []


def _search(repo_path, search_list, commits):
    """Return a list per commit of a list of all files in in the commit
    matching the critiria
    """
    search_string = _create_search_string(list(search_list))
    matches = []
    logger.info('Scanning {0} for {1} string(s)...'.format(
        repo_path, len(search_list)))
    for commit in commits:
        matches.append(_search_commit(repo_path, commit, search_string))
    return matches


def _create_search_string(search_list):
    logger.debug('Generating git grep-able search string...')
    unglobbed_search_list = ["'{0}'".format(item) for item in search_list]
    search_string = ' --or -e '.join(unglobbed_search_list)
    return search_string


def _search_commit(repo_path, commit, search_string):
    try:
        matched_files = subprocess.check_output(
            'git -C {0} grep -l -e {1} {2}'.format(
                repo_path, search_string, commit), shell=True)
        return matched_files.splitlines()
    except subprocess.CalledProcessError:
        return []


def _write_results(results,
                   repo_path,
                   repo_name,
                   org_name,
                   results_file_path='here.json'):
    """Write the result to DB
    """
    db = TinyDB(
        results_file_path,
        indent=4,
        sort_keys=True,
        separators=(',', ': '))

    logger.info('Writing results to: {0}...'.format(
        results_file_path))
    for matched_files in results:
        for match in matched_files:
            try:
                commit_sha, filepath = match.rsplit(':', 1)
                username, email, commit_time = \
                    _get_user_details(commit_sha, repo_path)
                result = dict(
                    email=email,
                    filepath=filepath,
                    username=username,
                    commit_sha=commit_sha,
                    commit_time=commit_time,
                    repository_name=repo_name,
                    organization_name=org_name,
                    blob_url=constants.GITHUB_BLOB_URL.format(
                        org_name,
                        repo_name,
                        commit_sha, filepath)
                )
                # result_count += 1
                db.insert(result)
            except IndexError:
                # The structre of the output is
                # sha:filename
                # sha:filename
                # filename
                # None
                # We need both sha and filename and when we don't
                # get them we skip to the next
                pass


def _get_user_details(sha, repo_path):
    """Return user_name, user_email, commit_time
    per commit before write to DB
    """
    details = subprocess.check_output(
        "git -C {0} show -s  {1}".format(repo_path, sha), shell=True)
    name = utils.find_string_between_strings(details, 'Author: ', ' <')
    email = utils.find_string_between_strings(details, '<', '>')
    commit_time = utils.find_string_between_strings(
        details, 'Date:   ', '+').strip()
    return name, email, commit_time


def search(repo_url,
           source=None,
           pager=None,
           verbose=False,
           search_list=None,
           config_file=None,
           results_dir=None,
           print_result=False,
           cloned_repo_dir=None,
           consolidate_log=False,
           from_organization=False,
           remove_cloned_dir=False,
           no_sync=False,
           **kwargs):
    """API method init repo instance and search strings
    """
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    utils.assert_executable_exists('git')

    # source = handler.plugins_handle(
    #     config_file=config_file, plugins_list=source)

    # if not from_organization:
    # search_list = handler.merge_all_search_list(
    #     source=source,
    #     config_file=config_file,
    #     search_list=search_list)

    if not isinstance(search_list, list):
        raise SurchError('`search_list` must be of type list')
    if len(search_list) == 0:
        raise SurchError(
            'You must supply at least one string to search for')

    # start = time()
    repo_props = _get_repo_props(repo_url)
    repo_path = _get_repo(repo_url, repo_props['local_path'], no_sync)
    commit_shas = _get_all_commits(repo_path)
    # commits_count = len(commit_shas)
    results = _search(repo_path, search_list, commit_shas)
    # raise Exception(results)
    _write_results(results, repo_path, repo_props['name'], repo_props['org'])

    # total_time = utils.convert_to_seconds(start, time())

    # logger.info('Found {0} results in {1} commits'.format(
    #     result_count, commits_count))
    # logger.debug('Total time: {0} seconds'.format(total_time))
    # if 'pagerduty' in pager:
    #     handler.pagerduty_trigger(config_file=config_file,
    #                               log=results_file_path)
    # return results
