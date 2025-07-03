import asyncio
import base64
import gzip
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urljoin

import aiohttp
import requests
import urllib3
from aiohttp.client_exceptions import ClientError
from requests.exceptions import HTTPError, SSLError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Initialize logging
# Create logger
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

# Create console handler
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# Set formatter directly without a custom class
formatter = logging.Formatter("[%(levelname)s] %(message)s")
ch.setFormatter(formatter)

# Add handler to logger
log.addHandler(ch)

SCANNED_FILE_DIR = os.environ.get("REPORT_PATH", "/app/data/")


class Checkmarx:
    def __init__(self, env):
        self.env = env
        self.bearer_token = ""
        self.base_url = ""

    def _get_domain_auth_url(self, token):
        """
        Decodes a JWT token without verifying the signature.
        Returns the payload as a dictionary.
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError("Invalid JWT format")

            payload_b64 = parts[1]
            # Add base64 padding
            payload_b64 += "=" * (-len(payload_b64) % 4)
            decoded_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(decoded_bytes)

            auth_url = payload.get("iss")
            if not auth_url:
                raise ValueError("Missing 'iss' field in JWT payload")
            domain = auth_url.split("iam")[0]
            self.base_url = domain + "ast.checkmarx.net"
            return auth_url
        except Exception as e:
            log.error(f" Invalid API key   ")
            return None

    def _get_checkmarx_bearer_token(self):
        """
        Fetch authentication token for Checkmarx.

        :param region_name: Region as a string (e.g., "US", "EU")
        :param tenant_name: Tenant account name
        :param token: Token used to get access-token refresh authentication
        :return: JSON response containing the new token
        """
        try:
            log.info(f" Fetching bearer token ... ")
            auth_url = self._get_domain_auth_url(self.env["CX_API_KEY"])
            if auth_url is None:
                return None
            url = f"{auth_url}/protocol/openid-connect/token"
            payload = {
                "grant_type": "refresh_token",
                "client_id": "ast-app",
                "refresh_token": self.env["CX_API_KEY"],
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            try:
                response = requests.post(
                    url,
                    data=payload,
                    headers=headers,
                    verify=False,
                )
            except SSLError as ssl_err:
                response = requests.post(url, data=payload, headers=headers)

            log.info(f" Fetching authentication token for Checkmarx... ")
            if response.status_code == 200:
                return response.json().get("access_token")
            else:
                response.raise_for_status()
            return None
        except KeyError:
            log.error(f" Invalid region: {self.domain}   ")
            return None
        except requests.RequestException as e:
            log.error(f" Invalid API key: {str(e)}   ")
            return None

    MAX_RETRIES = 3  # Maximum retry attempts

    async def _fetch_data(self, endpoint, flag=True, project_name="*"):
        if flag:
            log.info(f"['{project_name}'] Fetching data for endpoint: {endpoint} ")

        url = f"{self.base_url}/{endpoint}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.bearer_token}",
        }
        response = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, ssl=False) as response:
                        status = response.status
                        json_data = await response.json(content_type=None)
                        if status == 200:
                            return json_data

                        if status == 401:  # Unauthorized
                            if attempt < self.MAX_RETRIES:
                                log.info(
                                    f"['{project_name}']  Unauthorized access. Retrying... ({attempt + 1}/{self.MAX_RETRIES}) ",
                                )
                                self.bearer_token = self._get_checkmarx_bearer_token()
                                headers["Authorization"] = f"Bearer {self.bearer_token}"
                                await asyncio.sleep(1)
                                continue
                            else:
                                log.error(
                                    "['{project_name}']  Maximum retry attempts reached. Authorization failed. ",
                                )
                                raise RuntimeError("Unauthorized")
                        if status == 400:
                            log.error(f"['{project_name}']  Bad request {json_data}  ")

                        if status == 403:
                            log.error(f"['{project_name}']  Forbidden : {status}  ")

                        if status == 404:
                            log.error(
                                f"['{project_name}']  Resource not found: {url}:  {response}  ",
                            )
                            sys.exit(1)
                        else:
                            log.error(f"['{project_name}']  Unknow error {json_data}  ")
                            sys.exit(1)
            except ClientError as e:
                log.warning(
                    f"['{project_name}']  Client error during fetch: {e}. Retrying... ({attempt + 1}/{self.MAX_RETRIES})",
                )
                await asyncio.sleep(1)
            except Exception as e:
                log.error(f"['{project_name}']  Unexpected error: {e}")
                sys.exit(1)

    def build_simple_or_regex(self, patterns):
        if not patterns or "" in patterns:
            return ".*"

        if isinstance(patterns, str):
            patterns = [patterns]

        regex_parts = []

        for pat in patterns:
            pat = pat.strip()
            if "*" in pat and not pat.startswith("*") and not pat.endswith("*"):
                # Case: abc*def → starts with abc and ends with def
                parts = pat.split("*", 1)
                prefix = re.escape(parts[0])
                suffix = re.escape(parts[1])
                regex_parts.append(f"{prefix}.*{suffix}")

            elif pat.startswith("*") and pat.endswith("*"):
                value = re.escape(pat.strip("*"))
                regex_parts.append(f".*{value}.*")

            elif pat.startswith("*"):
                value = re.escape(pat.lstrip("*"))
                regex_parts.append(f".*{value}$")

            elif pat.endswith("*"):
                value = re.escape(pat.rstrip("*"))
                regex_parts.append(f"^{value}.*")

            else:
                value = re.escape(pat)
                regex_parts.append(f"^{value}$")

        combined = "|".join(regex_parts)
        return combined

    def build_combined_regex(self, patterns):
        if not patterns:
            return None, False

        if isinstance(patterns, str):
            patterns = [patterns]

        # Trim all whitespace early
        patterns = [p.strip() for p in patterns]

        # Handle empty string logic
        if "" in patterns:
            if len(patterns) > 1:
                patterns = [p for p in patterns if p != ""]
            else:
                return None, False  # Only "" present

        include = []
        exclude = []
        match_all = False
        has_exclude = False

        for pat in patterns:
            if pat == "*":
                match_all = True
                continue

            is_exclude = pat.startswith("-")
            if is_exclude:
                has_exclude = True
            pat_core = pat.lstrip("-")

            if pat_core.startswith("*") and pat_core.endswith("*"):
                value = re.escape(pat_core.strip("*"))
                look = f"(?!.*{value})" if is_exclude else f"(?=.*{value})"

            elif pat_core.startswith("*"):
                value = re.escape(pat_core.lstrip("*"))
                look = f"(?!.*{value}$)" if is_exclude else f"(?=.*{value}$)"

            elif pat_core.endswith("*"):
                value = re.escape(pat_core.rstrip("*"))
                look = f"(?!^{value})" if is_exclude else f"(?=^{value})"

            else:
                value = re.escape(pat_core)
                look = f"(?!^{value}$)" if is_exclude else f"(?=^{value}$)"

            if is_exclude:
                exclude.append(look)
            else:
                include.append(look)

        # NEW RULE: if only excludes and no includes — inject match_all behavior
        if not include and exclude:
            match_all = True

        if match_all:
            regex = "^" + "".join(exclude) + ".*$"
        elif include:
            regex = "^" + "".join(exclude) + ".*(" + "|".join(include) + ").*$"
        else:
            regex = "^" + "".join(exclude) + ".*$"
        return re.compile(regex), has_exclude

    def build_rule_sets(self, rules):
        exclude_patterns = []
        include_project = []
        empty_branch = True
        rule = []
        try:
            total_rule = len(rules)
            for proj, branch in rules.items():
                exclude_flag = True
                rule_dict = {"project": "", "branch": "", "is_exclude": False}
                proj = proj.strip()
                is_exclude = proj.startswith("-")
                if is_exclude and total_rule > 1:
                    exclude_flag = False
                    pat_core = proj.lstrip("-")
                    exclude_patterns.append(pat_core)

                proj_branch, is_exclude_branch = self.build_combined_regex(branch)

                if proj_branch and exclude_flag:
                    rule_dict["branch"] = proj_branch
                    rule_dict["is_exclude"] = is_exclude_branch
                    empty_branch = False

                if total_rule == 1:
                    rule_dict["project"], _ = self.build_combined_regex(proj)
                    rule.append(rule_dict)
                    if not is_exclude:
                        include_project.append(proj)

                elif not is_exclude:
                    include_project.append(proj)
                    rule_dict["project"], _ = self.build_combined_regex(proj)
                    rule.append(rule_dict)

            include_project = self.build_simple_or_regex(include_project)
            exclude_patterns, _ = self.build_combined_regex(exclude_patterns)

            return empty_branch, exclude_patterns, rule, include_project
        except Exception as e:
            raise ValueError(f"Invalid format CX_PROJECT: {e}")

    async def _fetch_all_project(self, name_regex=None):
        """
        Fetch all matching projects from Checkmarx API with optional name regex.
        :param name_regex: Optional regex pattern to filter project names
        :return: List of project dictionaries
        """
        log.info(" Fetching project details from server... ")

        limit = 100
        offset = 0
        all_projects = []
        endpoint = f"api/projects/?limit={limit}&offset={offset}"
        if name_regex:
            endpoint += f"&name-regex={name_regex}"

        data = await self._fetch_data(endpoint, flag=False)
        if isinstance(data, dict) and not data.get("projects"):
            return all_projects
        total_count = data.get("totalCount")
        if total_count is not None:
            all_projects.extend(data.get("projects", []))

        tasks = []
        for offset in range(limit, total_count, limit):
            endpoint = f"api/projects/?limit={limit}&offset={offset}"
            if name_regex:
                endpoint += f"&name-regex={name_regex}"
            tasks.append(self._fetch_data(endpoint, flag=False))

        page_results = await asyncio.gather(*tasks)

        for result in page_results:
            if result.get("projects"):
                all_projects.extend(result.get("projects", []))

        return all_projects

    async def _fetch_scan_detail(self, scan_id, project_name):
        endpoint = f"api/scans/{scan_id}"
        scan_detail = await self._fetch_data(endpoint, project_name=project_name)
        return scan_detail

    def _fix_isoformat(self, iso_str):
        if "Z" in iso_str:
            iso_str = iso_str.replace("Z", "+00:00")
        date_part, time_part = iso_str.split("T")
        time_main, offset = time_part.split("+")
        if "." in time_main:
            t, micro = time_main.split(".")
            micro = micro.ljust(6, "0")
            time_main = f"{t}.{micro}"
        return datetime.fromisoformat(f"{date_part}T{time_main}+{offset}")

    async def _fetch_last_scan_id(self, project_id, branch_names, project_name):
        scan_ids = []
        scan_details = []

        if not branch_names:
            branch_names = [None]  # So we loop once without appending any branch
        for branch_name in branch_names:
            api = f"api/projects/last-scan?offset=0&limit=20&project-ids={project_id}&"
            if branch_name:
                api += f"branch={branch_name}&"
            completed_url = api + "scan-status=Completed"
            partial_url = api + "scan-status=Partial"

            # Run both fetches concurrently
            scan_completed, scan_partial = await asyncio.gather(
                self._fetch_data(completed_url, project_name=project_name),
                self._fetch_data(partial_url, project_name=project_name),
            )
            try:
                if not scan_completed and not scan_partial:
                    log.info(
                        f"['{project_name}']   No completed or partial scans found for branch '{branch_name or 'default'}'. ",
                    )
                    continue

                key = None

                dt_completed = dt_partial = None

                if scan_completed:
                    key = list(scan_completed.keys())[0]
                    dt_completed = self._fix_isoformat(scan_completed[key]["createdAt"])

                if scan_partial:
                    key = list(scan_partial.keys())[0]
                    dt_partial = self._fix_isoformat(scan_partial[key]["createdAt"])

                # Compare timestamps and decide which scan ID to use
                if dt_completed and (not dt_partial or dt_completed > dt_partial):
                    log.info(f"['{project_name}']  Scan ID from completed scan. ")
                    scan_id = scan_completed[key]["id"]
                elif dt_partial:
                    log.info("f['{project_name}']  Scan ID from partial scan. ")
                    scan_id = scan_partial[key]["id"]
                else:
                    continue

                scan_detail = await self._fetch_scan_detail(scan_id, project_name)
                scan_ids.append(scan_id)
                scan_details.append(scan_detail)

            except Exception as e:
                log.error(f" Branch: {branch_name or 'default'} {e}  ")
        return scan_ids, scan_details

    async def _get_result(self, scan_id, project_name):
        """
        Fetch all result for a scan_id.
        :return: JSON response containing scan data
        """
        log.info(
            f"['{project_name}']  Fetching checkmarx scan result for a scan_id:{scan_id} ",
        )

        findings = []
        limit = 1000
        offset = 0
        endpoint = f"api/results/?limit={limit}&offset={offset}&scan-id={scan_id}"
        data = await self._fetch_data(endpoint, project_name=project_name)
        total_count = data.get("totalCount")
        if total_count is not None:
            findings.extend(data.get("results", []))

        tasks = []
        for offset in range(limit, total_count, limit):
            endpoint = f"api/results/?limit={limit}&offset={offset}&scan-id={scan_id}"
            tasks.append(self._fetch_data(endpoint, project_name=project_name))

        page_results = await asyncio.gather(*tasks)
        for result in page_results:
            if data.get("results"):
                findings.extend(data.get("results", []))

        result = {
            "scan_id": scan_id,
            "finding": findings,
            "query_desc": await self._get_sast_query_detail(findings, project_name),
        }

        return result

    async def _get_sast_query_detail(self, data, project_name):
        log.info(f"['{project_name}']  Fetching data for query_description ")
        query_ids = []
        seen = set()
        for item in data:
            if item.get("type", "") == "sast":
                qid = item.get("data", {}).get("queryId")
                if qid and qid not in seen:
                    seen.add(qid)
                    query_ids.append(qid)

        query_description = {}
        tasks = []

        for i in range(0, len(query_ids), 1000):
            batch = query_ids[i : i + 1000]
            query_string = "&".join(f"ids={qid}" for qid in batch)
            api = f"api/queries/descriptions?{query_string}"
            tasks.append(self._fetch_data(api, flag=False))

        page_results = await asyncio.gather(*tasks)

        for query_data in page_results:
            for item in query_data:
                qid = item.get("queryId")
                if qid:
                    query_description[qid] = item

        return query_description

    def _fetch_branches(self, project_id, branch_name=None):
        offset = 0
        limit = 1000
        all_branches = []
        api = f"api/projects/branches?project-id={project_id}"
        if branch_name:
            api += f"&branch-name={branch_name}"

        while True:  # Return none if there is no data
            endpoint = api + f"&offset={offset}&limit={limit}"
            data = asyncio.run(self._fetch_data(endpoint, flag=True))
            if not data:  # Handles None, empty list, or empty dict
                break
            all_branches += data
            offset += limit
        return all_branches

    def pre_process_project(self):
        primary_branch = self.env.get("primary_branch")
        empty_branch, exclude_patterns, rules, include_project = self.build_rule_sets(
            self.env["CX_PROJECT"],
        )
        projects = asyncio.run(self._fetch_all_project(include_project))
        project_result = []
        log_info = {}
        for item in projects:
            name = item["name"]
            project_id = item["id"]

            if exclude_patterns and exclude_patterns.match(name):
                continue

            branches = []
            branch_set = set()
            matched_any = True

            if primary_branch:
                primary_branch_name = item.get("mainBranch")

                if not primary_branch_name:
                    continue

                matched_any = False
                branches = [primary_branch_name]
            elif not empty_branch:
                matched_any = False
                branches = self._fetch_branches(project_id)

            for branch in branches:
                for rule in rules:
                    if rule["project"].match(name):
                        if rule["branch"] and rule["branch"].match(branch):
                            matched_any = True
                            if rule["is_exclude"] and branch in branch_set:
                                branch_set.remove(branch)
                            else:
                                branch_set.add(branch)
                        elif not rule["branch"]:
                            matched_any = True

            if matched_any:
                item["branch_name"] = list(branch_set)
                log_info[name] = item["branch_name"]
                project_result.append(item)
        print("-" * 30, "Collecting Data from these Projects", "-" * 30)
        for proj, branch in log_info.items():
            print(f"Project: {proj} -> Branch: {branch}")

        if not project_result:
            print(f"No project found with give env variable CX_PROJECT: {self.env["CX_PROJECT"]}")
            sys.exit(1)
            
        return project_result

    def run(self):
        self.bearer_token = self._get_checkmarx_bearer_token()
        if not self.bearer_token:
            log.error("Failed to retrieve Checkmarx bearer token.")
            return
        message_lock = threading.Lock()
        message = []
        project_details = self.pre_process_project()
        print("-" * 90)

        def process_project(project):
            nonlocal message
            project_name = project.get("name")
            branch_name = project.get("branch_name", [])
            project_id = project.get("id")
            data = project

            scan_ids, scan_info = asyncio.run(
                self._fetch_last_scan_id(
                    project_id,
                    branch_names=branch_name,
                    project_name=project_name,
                ),
            )
            if not scan_ids:
                msg = f"['{project_name}']  No scans found"
                if branch_name:
                    msg += f" branch:{branch_name}"
                log.warning(f"{msg}")
                with message_lock:
                    message.append(msg)
                return

            data["scan"] = scan_info
            data["result"] = []

            for scan_id in scan_ids:
                result = asyncio.run(self._get_result(scan_id, project_name))
                data["result"].append(result)

            try:
                time_suffix = str(time.time())
                issues_file = os.path.join(
                    SCANNED_FILE_DIR,
                    f"CHECKMARX-CX-{time_suffix}.json",
                )
                with open(issues_file, "w") as f:
                    json.dump(data, f, indent=2)
                log.info(f"['{project_name}']  Results written to {issues_file} ")
                upoad_status, msg = self.upload_results(issues_file, project_name)
                if upoad_status:
                    msg = f"['{project_name}'] Results successfully uploaded"
                    if branch_name:
                        msg += f" for :{branch_name}"
                else:
                    log.error(f"['{project_name}']  Upload failed: {msg} ")
                    sys.exit(1)

                with message_lock:
                    message.append(msg)
            except Exception as e:
                log.error(
                    f"Error while saving or uploading results for {project_name}: {e}",
                )
            finally:
                ## remove the json file
                if os.path.exists(issues_file):
                    os.remove(issues_file)

        cpu_count = os.cpu_count() or 2
        max_workers = min(8, cpu_count * 2)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(process_project, project) for project in project_details
            ]

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    log.error(f"Thread raised an error: {e}")

        print("-" * 30, "Result", "-" * 30)
        print("\n".join(message))

    def upload_results(self, result_file, project_name):
        log.info(
            f"['{project_name}']  Uploading the result to AccuKnox control plane... ",
        )
        """Upload the result JSON to the specified endpoint."""
        try:
            # Create temp gzip file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as tmp:
                compressed_path = tmp.name
            with open(result_file, "rb") as f_in, gzip.open(
                compressed_path,
                "wb",
            ) as f_out:
                shutil.copyfileobj(f_in, f_out)

            with open(result_file, "rb") as file:
                data = file.read()
                files = {"file": (result_file, data)}
                url = f"{self.env['AK_ENDPOINT']}/api/v1/artifact/"
                headers = {
                    "Tenant-Id": self.env["AK_TENANT_ID"],
                    "Authorization": f"Bearer {self.env['AK_TOKEN']}",
                }
                params = {
                    "tenant_id": self.env["AK_TENANT_ID"],
                    "data_type": "CX",
                    "save_to_s3": "false",
                    "label_id": self.env["AK_LABEL"],
                }

                last_exc = None
                for attempt in range(1, 4):
                    try:
                        try:
                            response = requests.post(
                                url=url,
                                files=files,
                                headers=headers,
                                params=params,
                                verify=False,
                            )
                        except SSLError:
                            response = requests.post(
                                url=url,
                                files=files,
                                headers=headers,
                                params=params,
                            )
                        response.raise_for_status()
                        log.info(
                            f"['{project_name}']  Upload successful on attempt {attempt}. Status: {response.status_code} ",
                        )
                        break
                    except (requests.exceptions.RequestException, HTTPError) as e:
                        last_exc = e
                        time.sleep(1)
                        log.warning(
                            f"['{project_name}']  Upload attempt {attempt} failed: {e}",
                        )
                else:
                    # all attempts failed
                    raise last_exc
            response.raise_for_status()
            log.info(
                f"['{project_name}']  Upload successful. Response: {response.status_code} ",
            )
            return True, ""
        except HTTPError as http_err:
            msg = f"['{project_name}']  HTTP error: received status code: {response.status_code}, Response body: {response.text}"
            log.error(f" {msg}  ")
            return False, msg
        except requests.exceptions.RequestException as req_err:
            msg = f"['{project_name}']  Network error: failed to complete request. Details: {req_err}"
            log.error(f" {msg}  ")
            return False, msg
        except Exception as err:
            msg = f"['{project_name}']  Unexpected error: {err}"
            log.error(f" {msg}  ")
            return False, msg
        finally:
            # Remove temp gzip file
            if os.path.exists(compressed_path):
                os.remove(compressed_path)


REQUIRED_ENV_VARS = [
    "CX_PROJECT",
    "CX_API_KEY",
    "AK_ENDPOINT",
    "AK_LABEL",
    "AK_TENANT_ID",
    "AK_TOKEN",
]


def get_env_config():
    missing = [key for key in REQUIRED_ENV_VARS if not os.environ.get(key)]
    if missing:
        print(
            f"❌ Missing required environment variables: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    config = {key: os.environ.get(key) for key in REQUIRED_ENV_VARS}
    # Parse CX_PROJECT as from comma-separated string
    raw_project_map = os.environ.get("CX_PROJECT", "").strip()
    try:
        project_name = json.loads(raw_project_map)
    except Exception as e:
        raise ValueError(f"Invalid format CX_PROJECT: {e}")

    config["CX_PROJECT"] = project_name
    config["primary_branch"] = (
        os.environ.get("CX_PRIMARY_BRANCH", "false").strip().lower() == "true"
    )

    return config


if __name__ == "__main__":
    env = get_env_config()
    cc = Checkmarx(env)
    cc.run()
