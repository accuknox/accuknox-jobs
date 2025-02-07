# from bs4 import BeautifulSoup
import json
import re
import logging
import os
import shutil
import subprocess
import tarfile
import time
import traceback
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date

import requests

SCANNED_FILE_DIR = './'

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def prereq():
    """
    Install NodeJS which is needed to run SonarQube.
    """
    try:
        return "" # Everything installed using Dockerfile
        subprocess.run(
            "curl -sL https://s3.amazonaws.com/scripts.accuknox.com/nodesource_setup.sh -o /tmp/nodesource_setup.sh",
            shell=True,
        )
        subprocess.run("bash /tmp/nodesource_setup.sh", shell=True)
        subprocess.run("apt-get -o DPkg::Lock::Timeout=-1 update -y", shell=True)
        #__salt__["pkg.install"]("nodejs")
        #__salt__["pkg.install"]("python3-pip")
        #__salt__["pip.install"]("beautifulsoup4")
        #__salt__["pip.install"]("lxml")

        return ""
    except:
        error = traceback.format_exc()
        log.error(error)
        return error

def sq_api(api, params, auth_token=None):
    log.info("calling api={}".format(api))
    try:
        response = requests.get(
            api,
            params=params,
            auth=(auth_token, ""),
        )
    except Exception as e:
        err = "error calling SonarQube API."
        log.error(f"{err} + {e}")
        raise

    log.info("api={} resp={}".format(api,response.status_code))
    if response.status_code == 401:
        raise ValueError("sonarqube auth error")
    if response.status_code != 200:
        raise ValueError("sonarqube api error")
    return response.status_code, response.json()

def _get_results(key, auth_token=None, sonar_url=None, branch=None):
    """
     Gather scan results for a project from the SonarQube API

    key:            The SonarQube project key/name to search for on the SonarQube server
    token:          An authentication token with privileges to access the project key on
                     the SonarQube server
    sonar_url:      The URL of the SonarQube server where scan results are sent.
    """

    # salt_wrapper = SaltWrapper()

    # Gather variables for HTTP Query
    api = urllib.parse.urljoin(sonar_url, "api/issues/search")
    params = {
        "componentKeys": key,
        "ps": 500,
        "p": 1,
        "additionalFields": "comments",
        "resolved": "false",
    }
    if branch:
        params.update({"branch": branch})

    # Query the API to get total number of results
    try:
        code, issues = sq_api(api, params, auth_token)
    except Exception as e:
        err = "An error occured when connecting to the SonarQube API."
        log.error(f"{err} + {e}")
        return False, None, err

    total = issues.get("total", 0)
    issues = issues.get("issues", [])

    results = "{ "

    if branch:
        results += '"branch": "{}",'.format(branch)

    if total == 0:
        log.error("No SonarQube results for {} on {}.".format(key, api))
        results += '"issues": [], '

    else:
        results += '"issues": ['

        results = _build_issues_string(issues, auth_token, results, sonar_url)

        if total > 500:  # maximum page size for SonarQube API
            # Continue to query API until all issues have been retrieved
            while params["p"] < 20:
                params["p"] += 1
                try:
                    code, issues = sq_api(api, params, auth_token)
                except Exception as e:
                    err = "An error occured when connecting to the SonarQube API."
                    log.error(f"{err} + {e}")
                    return False, None, err

                issues = issues.get("issues", [])
                if issues:
                    # Add issues on current page to total issues
                    results = _build_issues_string(
                        issues,
                        auth_token,
                        results,
                        sonar_url,
                    )
                else:
                    break
        results = results[:-2]
        results += "], "

    # Get Security Hotspots
    params = {"projectKey": key, "ps": 500, "p": 1, "status": "TO_REVIEW"}
    if branch:
        params.update({"branch": branch})

    try:
        code, hotspots = sq_api("{}/api/hotspots/search".format(sonar_url), params, auth_token)
    except Exception as e:
        err = "An error occured when connecting to the SonarQube API."
        log.error(f"{err} + {e}")
        return False, None, err

    if "errors" in hotspots:
        try:
            error = hotspots["errors"][0]["msg"]
        except Exception as e:
            return False, None, "An unspecified error occurred."
        if error == "Insufficient privileges":
            err = "Token has insufficient privileges to list hotspots. This may be because you are using the built-in Administrator user."
            log.error(err)
            return False, None, err
        else:
            return False, None, error

    total = hotspots["paging"]["total"]

    if total == 0:
        results = results[:-2]
        results += "}"

    elif total > 0:
        results += '"hotspots": ['

        hotspots = hotspots["hotspots"]

        results = _build_issues_string(hotspots, auth_token, results, sonar_url, True)

        if total >= 500:
            while params["p"] < 20:
                params["p"] += 1
                try:
                    code, hotspots = sq_api("{}/api/hotspots/search".format(sonar_url), params, auth_token)
                except Exception as e:
                    err = "An error occured when connecting to the SonarQube API."
                    log.error(f"{err} + {e}")
                    return False, None, err

                hotspots = hotspots["hotspots"]
                if hotspots:
                    # Add issues on current page to total issues
                    results = _build_issues_string(
                        hotspots,
                        auth_token,
                        results,
                        sonar_url,
                        True,
                    )
                else:
                    break
        results = results[:-2]
        results += "]}"

    # Write results to file
    # RJ 08-02-2025 issues_file = os.path.join(f"{SCANNED_FILE_DIR}", "SQ-{}.json".format(key))
    issues_file = os.path.join(f"{SCANNED_FILE_DIR}", "SQ-{}-{}.json".format(key, branch.replace("/", "_")))
    with open(issues_file, "w") as f:
        f.write(results)

    return True, issues_file, "Success."


def _build_issues_string(issues, auth_token, results, sonar_url, hotspots=False):
    from bs4 import BeautifulSoup

    for issue in issues:
        hasSnippet = True
        issueKey = issue["key"]
        try:
            line = issue["line"]
        except Exception as e:
            try:
                textRange = issue["textRange"]
                line = textRange["startLine"]
            except Exception as e:
                hasSnippet = False
        component = issue["component"]
        if hotspots:
            params = {"hotspot": issueKey}
            success = False
            while not success:
                try:
                    code, data = sq_api("{}/api/hotspots/show".format(sonar_url), params, auth_token)
                    success = True
                except Exception as e:
                    time.sleep(5)
            if "rule" in data:
                rule = data["rule"]
                if "name" in rule:
                    name = rule["name"]
                else:
                    name = "None"
                if "riskDescription" in rule:
                    riskDescription = rule["riskDescription"]
                else:
                    riskDescription = "None"
                # soup = BeautifulSoup(riskDescription, 'lxml')
                # riskDescription = soup.get_text()
                if "vulnerabilityDescription" in rule:
                    vulnerabilityDescription = rule["vulnerabilityDescription"]
                else:
                    vulnerabilityDescription = "None"
                # soup = BeautifulSoup(vulnerabilityDescription, 'lxml')
                # vulnerabilityDescription = soup.get_text()
                if "fixRecommendations" in rule:
                    fixRecommendations = rule["fixRecommendations"]
                else:
                    fixRecommendations = "None"
                # soup = BeautifulSoup(fixRecommendations, 'lxml')
                # fixRecommendations = soup.get_text()

                issue.update({"name": name})
                issue.update({"riskDescription": riskDescription})
                issue.update({"vulnerabilityDescription": vulnerabilityDescription})
                issue.update({"fixRecommendations": fixRecommendations})
            issue.update({"comments": data.get("comment", [])})
        else:
            rule = issue["rule"]
            params = {"key": rule}
            if sq_org != "":
                params["organization"] = sq_org

            success = False
            while not success:
                try:
                    code, data = sq_api("{}/api/rules/show".format(sonar_url), params, auth_token)
                    success = True
                except Exception as e:
                    time.sleep(5)
            if "htmlDesc" in data["rule"]:
                description = data["rule"]["htmlDesc"]
            else:
                description = "No Description Available."
            issue.update({"description": description})
        if hasSnippet:
            params = {"issueKey": issueKey}
            success = False
            while not success:
                try:
                    code, data = sq_api("{}/api/sources/issue_snippets".format(sonar_url), params, auth_token)
                    success = True
                except Exception as e:
                    time.sleep(5)
            try:
                data = data[component]
                sources = data["sources"]
                fullSnippet = []
                for source in sources:
                    try:
                        line = source["line"]
                        code = source["code"]
                        space_count = len(code) - len(code.lstrip())
                        soup = BeautifulSoup(code, "lxml")
                        code = " " * space_count + soup.get_text()
                        lineSnippet = {"line": line, "code": code}
                        fullSnippet.append(lineSnippet)
                    except Exception as e:
                        error = traceback.format_exc()
                        log.error(error)
                issue.update({"snippet": fullSnippet})
            except Exception as e:
                error = traceback.format_exc()
                log.error(error)
        results += json.dumps(issue)
        results += ", "
    return results


def _handleMissingParam(param):
    """
    The function that return missing param
    """
    error = "The {} parameter is missing".format(param)
    log.error(error)
    return error


def run(
    key=None,
    auth_token=None,
    sonar_url=None,
    branch=None,
):
    """
    Execute a new SonarQube scan

       Parameters:
           key:             SonarQube project Key
           token:           The SonarQube authentication token used to create this project on the SonarQube server
           sonar_url:       The URL of the SonarQube server where scan results are sent,
                            defaults to https://sonar.isystematics.com
           branch:          Project branch to scan.
    """

    errorMessage = prereq()
    if errorMessage:
        return errorMessage

    if not key:
        return _handleMissingParam("key")
    if not auth_token:
        return _handleMissingParam("auth token")
    if not sonar_url:
        return _handleMissingParam("Sonar URL")
    if sonar_url.endswith("/"):
        sonar_url = sonar_url[:-1]

    # Determine code requirements based on Operating System of the Minion used
    result = False
    result, issues_file, error = _get_results(
        key=key,
        auth_token=auth_token,
        sonar_url=sonar_url,
        branch=branch,
    )
    if result:
        return "Success! Data written to {}".format(issues_file)
    log.error(error)
    return error


def get_all_results(
    auth_token=None,
    sonar_url=None,
):
    """
    Collects all projects on the SonarQube server. Collects all results on all branches.

       Parameters:
           token:           The SonarQube authentication token used to create this project on the SonarQube server
           sonar_url:       The URL of the SonarQube server where scan results are sent.
    """

    errorMessage = prereq()
    if errorMessage:
        return errorMessage

    if not auth_token:
        return _handleMissingParam("auth token")
    if not sonar_url:
        return _handleMissingParam("Sonar URL")
    if sonar_url.endswith("/"):
        sonar_url = sonar_url[:-1]

    api = urllib.parse.urljoin(sonar_url, "api/components/search")

    params = {"qualifiers": "TRK", "ps": 500, "p": 1}
    if sq_org != "":
        params["organization"] = sq_org

    log.info("sonarqube: initiating components search ...")
    try:
        code, response = sq_api(api, params, auth_token)
    except Exception as e:
        err = "An error occured when connecting to the SonarQube API."
        log.error(err)
        return err

    total = response["paging"]["total"]
    components = response["components"]

    global keys
    keys = []

    log.info("projects regex {}".format(sq_projects))
    for component in components:
        key = component["key"]
        x = re.search(sq_projects, key)
        if x == None:
            log.info("ignoring project {}".format(key))
            continue
        log.info("adding project: {}".format(key))
        keys.append(key)

    if total > 500:
        while True:
            params["p"] += 1
            try:
                code, response = sq_api(api, params, auth_token)
            except Exception as e:
                err = "An error occured when connecting to the SonarQube API."
                log.error(f"{err} + {e}")
                return err
            components = response["components"]
            if not components:
                break
            for component in components:
                keys.append(component["key"])

    file_list = []

    if len(keys) == 0:
        return "No projects found on the SonarQube server."

    log.info("projects found {0}".format(keys))

    for key in keys:
        api = urllib.parse.urljoin(sonar_url, "api/project_branches/list")

        params = {"project": key}

        try:
            code, response = sq_api(api, params, auth_token)
        except Exception as e:
            err = "An error occured when connecting to the SonarQube API."
            log.error(f"{err} + {e}")
            return err

        for item in response["branches"]:
            branch = item["name"]

            result = False
            result, issues_file, error = _get_results(
                key=key,
                auth_token=auth_token,
                sonar_url=sonar_url,
                branch=branch,
            )
            if result:
                file_list.append(issues_file)
            else:
                log.error(error)
                return error
    return "Success! Data written to {}".format(file_list)


def get_some_results(
    auth_token=None,
    sonar_url=None,
    page_size=None,
    page=None,
):
    """
    Collects a subset of scan results on the SonarQube server. Collects all branches.

       Parameters:
           token:           The SonarQube authentication token used to create this project on the SonarQube server
           sonar_url:       The URL of the SonarQube server where scan results are sent
    """

    errorMessage = prereq()
    if errorMessage:
        return errorMessage

    if not auth_token:
        return _handleMissingParam("auth token")
    if not sonar_url:
        return _handleMissingParam("Sonar URL")
    if not page_size:
        return _handleMissingParam("page size")
    if not page:
        return _handleMissingParam("page")
    if sonar_url.endswith("/"):
        sonar_url = sonar_url[:-1]

    api = urllib.parse.urljoin(sonar_url, "api/components/search")

    params = {"qualifiers": "TRK", "ps": page_size, "p": page}

    try:
        code, response = sq_api(api, params, auth_token)
    except Exception as e:
        err = "An error occured when connecting to the SonarQube API."
        log.error(f"{err} + {e}")
        return err

    total = response["paging"]["total"]
    components = response["components"]

    global keys
    keys = []

    for component in components:
        keys.append(component["key"])

    file_list = []

    if len(keys) == 0:
        return "No projects found. Check the page parameter."

    for key in keys:
        api = urllib.parse.urljoin(sonar_url, "api/project_branches/list")

        params = {"project": key}

        try:
            code, response = sq_api(api, params, auth_token)
        except Exception as e:
            err = "An error occured when connecting to the SonarQube API."
            log.error(f"{err} + {e}")
            return err

        for item in response["branches"]:
            branch = item["name"]

            result = False
            result, issues_file, error = _get_results(
                key=key,
                auth_token=auth_token,
                sonar_url=sonar_url,
                branch=branch,
            )
            if result:
                r.sadd(redis_write_key, issues_file)
                file_list.append(issues_file)
            else:
                log.error(error)
                return error
    return "Success! Data written to {}".format(file_list)


def get_all_results_main_branch(
    auth_token=None,
    sonar_url=None,
):
    """
    Collects all projects on the SonarQube server. Only collects results on the main branch.

       Parameters:
           token:           The SonarQube authentication token used to create this project on the SonarQube server
           sonar_url:       The URL of the SonarQube server where scan results are sent
    """

    errorMessage = prereq()
    if errorMessage:
        return errorMessage

    if not auth_token:
        return _handleMissingParam("auth token")
    if not sonar_url:
        return _handleMissingParam("Sonar URL")
    if sonar_url.endswith("/"):
        sonar_url = sonar_url[:-1]

    api = urllib.parse.urljoin(sonar_url, "api/components/search")

    params = {"qualifiers": "TRK", "ps": 500, "p": 1}

    try:
        response = requests.get(api, params=params, auth=(auth_token, ""))
    except Exception as e:
        pass
        log.error("An error occured when connecting to the SonarQube API.")
        return "An error occured when connecting to the SonarQube API."

    if response.status_code == 401:
        return "401 Unauthorized Error. Check SonarQube auth token."

    response = response.json()

    total = response["paging"]["total"]

    components = response["components"]

    global keys
    keys = []

    for component in components:
        keys.append(component["key"])

    if total > 500:
        while True:
            params["p"] += 1
            try:
                response = requests.get(api, params=params, auth=(auth_token, ""))
            except Exception as e:
                log.error("An error occured when connecting to the SonarQube API.")
                return "An error occured when connecting to the SonarQube API."
            response = response.json()
            components = response["components"]
            if not components:
                break
            for component in components:
                keys.append(component["key"])

    file_list = []

    if len(keys) == 0:
        return "No projects found on the SonarQube server."

    for key in keys:
        result = False
        result, issues_file, error = _get_results(
            key=key,
            auth_token=auth_token,
            sonar_url=sonar_url,
        )
        if result:
            file_list.append(issues_file)
        else:
            log.error(error)
            return error
    return "Success! Data written to {}".format(file_list)

if __name__ == '__main__':
    sq_url = os.environ.get("SQ_URL", "")
    sq_auth_token = os.environ.get('SQ_AUTH_TOKEN', "")
    sq_projects = os.environ.get('SQ_PROJECTS', ".*")
    sq_org = os.environ.get('SQ_ORG', "")
    SCANNED_FILE_DIR = os.environ.get('REPORT_PATH', "./")
    
    if sq_url == "" or sq_auth_token == "":
        log.error("SQ_URL or SQ_AUTH_TOKEN env var not specified")
        exit(1)
    log.info(f"SQ_ORG={sq_org}")
    get_all_results(sq_auth_token, sq_url)
