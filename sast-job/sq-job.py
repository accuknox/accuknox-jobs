import asyncio
import re
import aiohttp
from tqdm import tqdm
import json
import urllib.parse
import os
import traceback
import logging

# Initialize logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Global variables
pbar = None
SCANNED_FILE_DIR = os.environ.get('REPORT_PATH', '/app/data')

async def async_sq_api(session, api, params, auth_token=None):
    """Make an async API call to SonarQube"""
    global pbar
    if pbar is None:
        pbar = tqdm(desc="API Calls")
    try:
        pbar.update(1)
        auth = aiohttp.BasicAuth(auth_token, '')
        async with session.get(api, params=params, auth=auth) as response:
            if response.status == 401:
                raise ValueError("sonarqube auth error")
            if response.status != 200:
                raise ValueError("sonarqube api error")
            return await response.json()
    except Exception as e:
        log.error(f"Error calling SonarQube API: {e}")
        raise

async def _get_issues_batch(session, api, params, auth_token):
    """Get a batch of issues from SonarQube"""
    issues = await async_sq_api(session, api, params, auth_token)
    return issues.get("issues", [])

async def _get_hotspots_batch(session, api, params, auth_token):
    """Get a batch of security hotspots from SonarQube"""
    response = await async_sq_api(session, api, params, auth_token)
    return response.get("hotspots", [])

async def _get_issue_details(session, issue, sonar_url, auth_token, is_hotspot=False):
    """Get detailed information about an issue or security hotspot"""
    if is_hotspot:
        params = {"hotspot": issue["key"]}
        api = f"{sonar_url}/api/hotspots/show"
    else:
        params = {"key": issue["rule"]}
        if sq_org:
            params["organization"] = sq_org
        api = f"{sonar_url}/api/rules/show"

    max_retries = 3
    for attempt in range(max_retries):
        try:
            data = await async_sq_api(session, api, params, auth_token)
            if is_hotspot:
                if "rule" in data:
                    rule = data["rule"]
                    issue.update({
                        "name": rule.get("name", "None"),
                        "riskDescription": rule.get("riskDescription", "None"),
                        "vulnerabilityDescription": rule.get("vulnerabilityDescription", "None"),
                        "fixRecommendations": rule.get("fixRecommendations", "None"),
                        "comments": data.get("comment", [])
                    })
            else:
                if "htmlDesc" in data["rule"]:
                    description = data["rule"].get("htmlDesc", "No Description Available.")
                else:
                    description_sections = data["rule"].get("descriptionSections", [])
                    description = description_sections if description_sections else "No Description Available."
                issue.update({"description": description})
            break
        except Exception:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(5)

    return issue

async def _get_snippet(session, issue, sonar_url, auth_token):
    """Get the code snippet for an issue"""
    if "line" not in issue and "textRange" not in issue:
        return issue

    params = {"issueKey": issue["key"]}
    api = f"{sonar_url}/api/sources/issue_snippets"

    try:
        data = await async_sq_api(session, api, params, auth_token)
        component_data = data[issue["component"]]
        
        fullSnippet = []
        for source in component_data["sources"]:
            try:
                line = source["line"]
                code = source["code"]
                space_count = len(code) - len(code.lstrip())
                code = " " * space_count + code
                fullSnippet.append({"line": line, "code": code})
            except Exception:
                log.error(traceback.format_exc())
        
        issue["snippet"] = fullSnippet
    except Exception:
        log.error(traceback.format_exc())

    return issue

async def _process_issues(session, issues, auth_token, sonar_url, is_hotspots=False):
    """Process a list of issues or security hotspots"""
    tasks = []
    for issue in issues:
        tasks.append(_get_issue_details(session, issue, sonar_url, auth_token, is_hotspots))
        if not is_hotspots:
            tasks.append(_get_snippet(session, issue, sonar_url, auth_token))
    
    processed_issues = await asyncio.gather(*tasks)
    return processed_issues

async def _get_results_async(key, auth_token, sonar_url, branch=None):
    """
     Gather scan results for a project from the SonarQube API

    key:            The SonarQube project key/name to search for on the SonarQube server
    token:          An authentication token with privileges to access the project key on
                     the SonarQube server
    sonar_url:      The URL of the SonarQube server where scan results are sent.
    """

    async with aiohttp.ClientSession() as session:
        api = urllib.parse.urljoin(sonar_url, "api/issues/search")
        params = {
            "componentKeys": key,
            "ps": 500,
            "p": 1,
            "additionalFields": "comments",
            "resolved": "false",
        }
        if branch:
            params["branch"] = branch

        try:
            initial_response = await async_sq_api(session, api, params, auth_token)
            total_issues = initial_response.get("total", 0)
            all_issues = initial_response.get("issues", [])

            if total_issues > 500:
                remaining_pages = min((total_issues - 1) // 500, 19)
                tasks = []
                for page in range(2, remaining_pages + 2):
                    page_params = {**params, "p": page}
                    tasks.append(_get_issues_batch(session, api, page_params, auth_token))
                
                additional_issues = await asyncio.gather(*tasks)
                for issues in additional_issues:
                    all_issues.extend(issues)

            processed_issues = await _process_issues(session, all_issues, auth_token, sonar_url)

            # Get hotspots
            hotspots_api = f"{sonar_url}/api/hotspots/search"
            hotspot_params = {"projectKey": key, "ps": 500, "p": 1, "status": "TO_REVIEW"}
            if branch:
                hotspot_params["branch"] = branch

            hotspots_response = await async_sq_api(session, hotspots_api, hotspot_params, auth_token)
            if "errors" in hotspots_response:
                error = hotspots_response.get("errors", [{"msg": "An unspecified error occurred."}])[0]["msg"]
                if error == "Insufficient privileges":
                    err = "Token has insufficient privileges to list hotspots."
                    log.error(err)
                    return False, None, err
                return False, None, error

            total_hotspots = hotspots_response["paging"]["total"]
            all_hotspots = hotspots_response.get("hotspots", [])

            if total_hotspots > 500:
                remaining_pages = min((total_hotspots - 1) // 500, 19)
                tasks = []
                for page in range(2, remaining_pages + 2):
                    page_params = {**hotspot_params, "p": page}
                    tasks.append(_get_hotspots_batch(session, hotspots_api, page_params, auth_token))
                
                additional_hotspots = await asyncio.gather(*tasks)
                for hotspots in additional_hotspots:
                    all_hotspots.extend(hotspots)

            processed_hotspots = await _process_issues(session, all_hotspots, auth_token, sonar_url, True)

            # Build results JSON
            results = {
                **({"branch": branch} if branch else {}),
                "issues": processed_issues or [],
                "hotspots": processed_hotspots or []
            }

            # Write results to file
            issues_file = os.path.join(SCANNED_FILE_DIR, f"SQ-{key}.json")
            with open(issues_file, "w") as f:
                json.dump(results, f, indent=2)

            return True, issues_file, "Success."

        except Exception as e:
            error_msg = f"An error occurred when connecting to the SonarQube API: {str(e)}"
            log.error(error_msg)
            return False, None, error_msg

async def process_project(key, auth_token, sonar_url):
    """Process all branches of a project"""
    api = urllib.parse.urljoin(sonar_url, "api/project_branches/list")
    async with aiohttp.ClientSession() as session:
        params = {"project": key}
        try:
            response = await async_sq_api(session, api, params, auth_token)
            branches = [item["name"] for item in response["branches"]]
            results = []
            for branch in branches:
                result = await _get_results_async(key, auth_token, sonar_url, branch)
                if result[0]:
                    results.append(result[1])
                else:
                    raise Exception(result[2])
            return results
        except Exception as e:
            log.error(f"Error processing project {key}: {str(e)}")
            raise

def _handle_missing_param(param):
    """
    The function that return missing param
    """
    error = f"The {param} parameter is missing"
    log.error(error)
    return error

async def get_all_results_async(auth_token, sonar_url):
    if not all([auth_token, sonar_url]):
        missing = "auth token" if not auth_token else "Sonar URL"
        return _handle_missing_param(missing)

    sonar_url = sonar_url.rstrip('/')
    api = urllib.parse.urljoin(sonar_url, "api/components/search")
    params = {"qualifiers": "TRK", "ps": 500, "p": 1}
    
    if sq_org:
        params["organization"] = sq_org

    try:
        async with aiohttp.ClientSession() as session:
            response = await async_sq_api(session, api, params, auth_token)
            total = response["paging"]["total"]
            components = response["components"]
            
            all_keys = []
            for component in components:
                key = component["key"]
                if re.search(sq_projects, key):
                    all_keys.append(key)

            if total > 500:
                page = 2
                while True:
                    params["p"] = page
                    response = await async_sq_api(session, api, params, auth_token)
                    if not response["components"]:
                        break
                    for component in response["components"]:
                        key = component["key"]
                        if re.search(sq_projects, key):
                            all_keys.append(key)
                    page += 1

            if not all_keys:
                return "No projects found on the SonarQube server."

            tasks = []
            for key in all_keys:
                task = asyncio.create_task(process_project(key, auth_token, sonar_url))
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            file_list = []
            for result in results:
                if isinstance(result, list):
                    file_list.extend(result)
                else:
                    log.error(f"Error processing project: {str(result)}")
                    return f"Error processing project: {str(result)}"

            return f"Success! Data written to {file_list}"

    except Exception as e:
        error_msg = f"An error occurred: {str(e)}"
        log.error(error_msg)
        return error_msg

if __name__ == '__main__':
    sq_url = os.environ.get("SQ_URL", "")
    sq_auth_token = os.environ.get('SQ_AUTH_TOKEN', "")
    sq_projects = os.environ.get('SQ_PROJECTS', ".*")
    sq_org = os.environ.get('SQ_ORG', "")
    
    if not sq_url or not sq_auth_token:
        log.error("SQ_URL or SQ_AUTH_TOKEN env var not specified")
        exit(1)
    
    asyncio.run(get_all_results_async(sq_auth_token, sq_url))
