import base64
import gzip
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime

import requests
import urllib3
from requests.exceptions import HTTPError, SSLError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Initialize logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

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
            log.error(f"<error> Invalid API key </error>  ")
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
            log.info(f"<info> Fetching bearer token ... </info>")
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
                response = requests.post(url, data=payload, headers=headers, verify=False)
            except SSLError as ssl_err:
                response = requests.post(url, data=payload, headers=headers)

            log.info(f"<info> Fetching authentication token for Checkmarx... </info>")
            if response.status_code == 200:
                return response.json().get("access_token")
            else:
                response.raise_for_status()
            return None
        except KeyError:
            log.error(f"<error> Invalid region: {self.domain} </error>  ")
            return None
        except requests.RequestException as e:
            log.error(f"<error> Invalid API key: {str(e)} </error>  ")
            return None

    MAX_RETRIES = 3  # Maximum retry attempts

    def _fetch_data(self, endpoint):
        log.info(f"<info> Fetching data for endpoint: {endpoint} </info>")

        url = f"{self.base_url}/{endpoint}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.bearer_token}",
        }
        response = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.get(url, headers=headers, verify=False)
            except SSLError as ssl_err:
                response = requests.get(url, headers=headers)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 401:  # Unauthorized
                if attempt < self.MAX_RETRIES:
                    log.info(
                        f"<warning>Unauthorized access. Retrying... ({attempt + 1}/{self.MAX_RETRIES}) </warning>",
                    )
                    self.bearer_token = (
                        self._get_checkmarx_bearer_token()
                    )  # Refresh token
                    headers[
                        "Authorization"
                    ] = f"Bearer {self.bearer_token}"  # Update header

                else:
                    log.error(
                        "<error> Maximum retry attempts reached. Authorization failed. </error>",
                    )
                    raise RuntimeError
                    break
            if response.status_code == 400:
                log.error(f"<error> Bad request {response.json()} </error> ")

            if response.status_code == 403:
                log.error(f"<error> Forbidden : {response} </error> ")

            if response.status_code == 404:
                log.error(f"<error> Resource not found :  {response} </error> ")
            else:
                log.error(f"<error> Unknow error {response.json()} </error> ")

    def _fetch_checkmarx_projects(self, project=None):
        """
        Fetch projects from Checkmarx API.
        :return: JSON response containing project data
        """
        log.info(f"<info> Fetching projects details for {project} ... </info>")

        limit = 10
        offset = 0
        endpoint = f"api/projects/?limit={limit}&offset={offset}&names={project}"
        data = self._fetch_data(endpoint)
        if isinstance(data, dict):
            filteredTotalCount = data.get("filteredTotalCount")
            if not filteredTotalCount:
                log.info("<warning> Invalid project name </warning>")
            if data.get("projects"):
                project_data = data.get("projects")[0]
                return project_data, project_data.get("id")
            else:
                log.error(f"<error> Invalid project name: {project}. </error>")
                return {}, None
        else:
            log.error(f"<Info> There is unknown issue: {data} </error>")
            return {}, None

    def _fetch_scan_id(self, project_id, scan_date):
        log.info(
            f"<info> Fetching latest scan id for project: {project_id} and date: {scan_date}</info>",
        )
        # Convert to RFC 3339 format
        scan_date = scan_date.replace("+00:00", "Z")
        endpoint = f"api/scans/?statuses=Completed&statuses=Partial&project-id={project_id}&from-date={scan_date}"
        scans = self._fetch_data(endpoint)
        scan_id = []
        scan_detail = []
        for scan in scans.get("scans", []):
            scan_id.append(scan.get("id"))
            scan_detail.append(scan)
        return scan_id, scan_detail

    def _fetch_scan_detail(self, scan_id):
        endpoint = f"api/scans/{scan_id}"
        scan_detail = self._fetch_data(endpoint)
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

    def _validate_branch_name(self, project_id, name):
        endpoint = f"api/projects/branches?offset=0&project-ids={project_id}&branch-name={name}&limit=5"
        branch_names =  self._fetch_data(endpoint)
        if isinstance(branch_names, list) and name in branch_names:
            return True
        return False


    def _fetch_last_scan_id(self, project_id, branch_name):
        api = f"api/projects/last-scan?offset=0&limit=20&project-ids={project_id}&"
        if branch_name:
            api += f"branch={branch_name}&"
        endpoint_completed = api + "scan-status=Completed"
        scan_completed = self._fetch_data(endpoint_completed)

        endpoint_partial = api + "scan-status=Partial"
        scan_partial = self._fetch_data(endpoint_partial)
        try:
            # If both are empty, return [], {}
            log.info(
                f"<info> scan_completed: {scan_completed}, scan_partial: {scan_partial}. </info>",
            )
            if not scan_completed and not scan_partial:
                return [], []

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
                log.info("<info> Scan ID from completed scan. </info>")
                scan_id = scan_completed[key]["id"]
            elif dt_partial:
                log.info("<info> Scan ID from partial scan. </info>")
                scan_id = scan_partial[key]["id"]
            else:
                return [], []

            scan_detail = self._fetch_scan_detail(scan_id)
            return [scan_id], [scan_detail]
        except Exception as e:
            log.error(f"<error> {e} </error> ")
            return [], {}

    def _get_result(self, scan_id):
        """
        Fetch all result for a scan_id.
        :return: JSON response containing scan data
        """
        log.info(
            f"<info> Fetching checkmarx scan result for a scan_id:{scan_id} </info>",
        )

        all_result = {}
        all_result["scan_id"] = scan_id
        limit = 1000
        offset = 0
        endpoint = f"api/results/?limit={limit}&offset={offset}&scan-id={scan_id}"
        data = self._fetch_data(endpoint)
        if isinstance(data, dict):
            total_count = data.get("totalCount")
            if total_count is not None:
                all_result["finding"] = data.get("results", [])
                offset = math.ceil(total_count / limit)
            for count in range(1, offset):
                endpoint = f"api/results/?limit={limit}&offset={count}&scan-id={scan_id}"
                data = self._fetch_data(endpoint)
                if isinstance(data, dict) and data.get("results"):
                    all_result["finding"] += data.get("results", [])

            query_desc = self._get_sast_query_detail(all_result)
            all_result["query_desc"] = query_desc
        return all_result

    def _get_sast_query_detail(self, data):
        query_ids = set()
        for item in data.get("finding", []):
            if item.get("type", "") == "sast" and item.get("data", {}).get("queryId"):
                query_ids.add(item.get("data", {}).get("queryId"))

        query_description = {}
        query_ids = list(query_ids)
        batch_size = 500
        for i in range(0, len(query_ids), batch_size):
            batch = query_ids[i:i + batch_size]
            query_params = "&".join(f"ids={qid}" for qid in batch)
            api = f"api/queries/descriptions?{query_params}"
            try:
                query_data = self._fetch_data(api)
                for item in query_data:
                    if "queryId" in item:
                        query_description[item["queryId"]] = item
            except Exception as e:
                log.error(f"Failed to fetch query descriptions for batch starting at index {i}: {e}")

        return query_description

    def run(self):
        self.bearer_token = self._get_checkmarx_bearer_token()
        if not self.bearer_token:
            log.error("Failed to retrieve Checkmarx bearer token.")
            return
        log_info = []
        for project_name, branch_name in self.env["CX_PROJECT_NAMES"].items():
            print("-"*90)
            data, project_id = self._fetch_checkmarx_projects(project=project_name)
            if not project_id:
                msg = f"Invalid Project Name '{project_name}'"
                log.warning(f"<warning> {msg} </warning>")
                log_info.append(msg)
                continue
            if branch_name:
                if not self._validate_branch_name(project_id, name=branch_name):
                    msg = f"Invalid branch name '{branch_name}' for project '{project_name}'"
                    log.error(f"<error> {msg} </error>")
                    log_info.append(msg)
                    continue
                log.info(f"Validated branch name '{branch_name}' for project '{project_name}'.")

            scan_ids, scan_info = self._fetch_last_scan_id(project_id, branch_name=branch_name)
            if not scan_ids:
                msg = f"No scans found for project '{project_name}'"
                if branch_name:
                    msg+=f" branch:{branch_name}"
                log.warning(f"<warning> {msg} </warning>")
                log_info.append(msg)
                continue

            data["scan"] = scan_info
            data["result"] = [self._get_result(scan_id) for scan_id in scan_ids]
            try:
                time_suffix = str(time.time())
                issues_file = os.path.join(SCANNED_FILE_DIR, f"CHECKMARX-CX-{time_suffix}.json")
                with open(issues_file, "w") as f:
                    json.dump(data, f, indent=2)
                log.info(f"<info> Results written to {issues_file} </info>")
                self.upload_results(issues_file)
                msg = "Results uploaded for project '{project_name}'"
                if branch_name:
                    msg+=f":{branch_name}"
                log_info.append(msg)
                ## remove the json file
                if os.path.exists(issues_file):
                    os.remove(issues_file)
            except Exception as e:
                log.error(f"Error while saving or uploading results for {project_name}: {e}")
        print("-"*30,"Result","-"*30)
        print("\n".join(log_info))

    def upload_results(self, result_file):
        log.info(f"<info> Uploading the result to AccuKnox control plane... </info>")
        """Upload the result JSON to the specified endpoint."""
        try:
                    # Create temp gzip file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as tmp:
                compressed_path = tmp.name
            with open(result_file, 'rb') as f_in, gzip.open(compressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

            with open(result_file, 'rb') as file:

                url = f"{self.env["AK_ENDPOINT"]}/api/v1/artifact/"
                headers={
                        "Tenant-Id": self.env["AK_TENANT_ID"],
                        "Authorization": f"Bearer {self.env["AK_TOKEN"]}"
                    }
                params={
                        "tenant_id": self.env["AK_TENANT_ID"],
                        "data_type": "CX",
                        "save_to_s3": "false",
                        "label_id": self.env["AK_LABEL"],
                    }
                files = {'file': (result_file, file)}
                try:
                    response = requests.post(url=url, files=files, headers=headers, params= params, verify=False)
                except SSLError:
                    response = requests.post(url=url, files=files, headers=headers, params= params)
            response.raise_for_status()
            log.info(f"<info> Upload successful. Response: {response.status_code} </info>")
        except HTTPError as http_err:
           log.error(f"<error> Status code: {response.status_code}, Response: {response.text} </error>")
        except requests.exceptions.RequestException as req_err:
            log.error(f"<error>403 Request exception occurred: {req_err} </error>")
        except Exception as err:
            log.error(f"<error>Unexpected error occurred: {err} </error>")
        finally:
            # Remove temp gzip file
            if os.path.exists(compressed_path):
                os.remove(compressed_path)



REQUIRED_ENV_VARS = [
    "CX_PROJECT_NAMES",
    "CX_API_KEY",
    "AK_ENDPOINT",
    "AK_LABEL",
    "AK_TENANT_ID",
    "AK_TOKEN"
]


def get_env_config():
    missing = [key for key in REQUIRED_ENV_VARS if not os.environ.get(key)]
    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    config = {key: os.environ.get(key) for key in REQUIRED_ENV_VARS}

    # Parse CX_PROJECT_NAMES as from comma-separated string
    project_name =  os.environ.get("CX_PROJECT_NAMES","").strip()
    project_map = {}
    for item in project_name.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            key, value = item.split(":", 1)
            if key:
                project_map[key.strip()] = value.strip()
        else:
            project_map[item] = ""  # No branch specified

    config["CX_PROJECT_NAMES"] = project_map
    return config

if __name__ == "__main__":
    env = get_env_config()
    cc = Checkmarx(env)
    cc.run()
