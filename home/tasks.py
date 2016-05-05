"""
Celery tasks to be run in the background
"""


from __future__ import absolute_import
from celery import shared_task
import sys

from uploader import upload
from uploader import job_status

from bundler import bundle

from home import tar_man 

import os

from home.task_comm import task_error, task_state

CLEAN_TAR = True

def clean_target_directory(target_dir='', server='', user='', password=''):
    """
    deletes local files that have made it to the archive
    """

    # remove old files that were not uploaded
    tar_man.remove_orphans(target_dir)

    # get job list from file
    jobs = tar_man.job_list(target_dir)

    if not jobs:
        return

    # fake job list
    #jobs = ['2001066', '2001067','2001068']

    # get jobs state from database
    jobs_state = job_status(protocol="https",
                            server=server,
                            user=user,
                            password=password,
                            job_list=jobs)

    # fake job state
    #jobs_state = '[{?20001066? : {?state_name?:?Received?, ?state?:?1"}},
    #            {?20001067? : {?state_name?:?Available?, ?state?:?5"}},
    #            {?20001068? : {?state_name?:?Available?, ?state?:?5"}}]'
    if jobs_state:
        err_str = tar_man.clean_tar_directory(target_dir, jobs_state)
        return err_str
    else:
        return 'unable to fetch job status'


@shared_task
def ping():
    """
    check to see if the celery task process is started.
    """
    print "Pinged!"
    task_state('PING', "Background process is alive")

#tag to show this def as a celery task
@shared_task
def upload_files(bundle_name='',
                 instrument_name='',
                 proposal='',
                 file_list=None,
                 bundle_size=0,
                 groups=None,
                 server='',
                 user='',
                 password=''):
    """
    task created on a separate Celery process to bundle and upload in the background
    status and errors are pushed by celery to the main server through RabbitMQ
    """
    target_dir = os.path.dirname(bundle_name)
    if not os.path.isdir(target_dir):
        current_task.update_state(state='ERROR', meta={'Status': 'Bundle directory does not exist'})

        task_state("PROGRESS", "Cleaning previous uploads")

    #clean tar directory
    if CLEAN_TAR:
        err_str = clean_target_directory(target_dir, server, user, password)
        if err_str:
            task_state('PROGRESS', err_str)

    # initial state pushed through celery
    task_state("PROGRESS", "Starting Bundle/Upload Process")

    bundle(bundle_name=bundle_name,
           instrument_name=instrument_name,
           proposal=proposal,
           file_list=file_list,
           groups=groups,
           bundle_size=bundle_size)

    task_state("PROGRESS", "Completed Bundling")

    task_state("PROGRESS", "Starting Upload")

    res = upload(bundle_name=bundle_name,
                 protocol="https",
                 server=server,
                 user=user,
                 password=password)

    if res is None:
        task_state("FAILURE",  "Uploader dieded. We don't know why it did")

    print >> sys.stderr, "upload completed"

    task_state("PROGRESS", "Completing Upload Process")

    if "http" in res:
        print "rename"
        job_id = tar_man.parse_job(res)
        print job_id
        tar_man.rename_tar_file(target_dir, bundle_name, job_id)

        print >> sys.stderr, "Status Page: {0}".format(res)
        task_state('SUCCESS', res)

        return res
    else:
        task_state("FAILURE", "No URL")
        return "Upload Failed"
