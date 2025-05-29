
import gzip
import html
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import time
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.exceptions import HTTPError, SSLError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Initialize logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SCANNED_FILE_DIR = os.environ.get("REPORT_PATH", "/app/data/")


class Checkmarx:
    def __init__(self, env):
        self.env = env
        self.base_url = env["BASE_URL"]
        self.bearer_token = ""

    MAX_RETRIES = 3  # Maximum retry attempts

    def _get_checkmarx_bearer_token(self):
        """
        Fetch authentication token for Checkmarx.
        """
        try:
            log.info(f"<info> Fetching bearer token ... </info>")

            payload = {
                "username": self.env["USER_NAME"],
                "password": self.env["PASSWORD"],
                "scope": self.env["SCOPE"],
                "grant_type": self.env["GRANT_TYPE"],
                "client_id": self.env["CLIENT_ID"],
                "client_secret": self.env["CLIENT_SECRET"],
            }
            url = urljoin(self.base_url, "/cxrestapi/auth/identity/connect/token")
            print(url)
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            response = ""
            try:
                response = requests.post(url, data=payload, headers=headers, verify=False)
            except SSLError:
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
            log.error(f"<error> Invalid Credential is provide: {str(e)} </error>  ")
            return None


    def _fetch_data(self, endpoint, flag=True):

        if flag:
            log.info(f"<info> Fetching data for endpoint: {endpoint} </info>")

        url = urljoin(self.base_url, f"/cxrestapi/{endpoint}")
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
                    log.warning(
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
                message = response.json()
                if isinstance(message, dict) and 'messageCode' in message:
                    if message["messageCode"]==47826:
                        log.error(f"<error> Invalid Project name </error> ")
                        sys.exit(1)
                    if message["messageCode"]==25016:
                        log.warning(f"<warning> Cx description not found for queryID : {endpoint} </warning> ")
                        return {}

                log.error(f"<error> Resource not found url-{url}: </error> ")
                if isinstance(message, dict) and 'messageDetails' in message :
                    log.error(f"<error> With {message["messageDetails"]}: </error> ")
                    sys.exit(1)
            else:
                log.error(f"<error> Unknow error {response.json()} </error> ")
                sys.exit(1)

    def _fetch_checkmarx_projects(self, project=None):
        """
        Fetch projects from Checkmarx API.
        :return: JSON response containing project data
        """
        log.info(f"<info> Fetch a projects details from Checkmarx </info>")
        limit = 1
        offset = 0
        endpoint = f"projects/?limit={limit}&offset={offset}&projectName={project}"
        data = self._fetch_data(endpoint)
        if isinstance(data, list) and len(data) > 0:
            project_data = data[0]
            return project_data, project_data.get("id")
        else:
            log.error(f"<Info> There is unknown issue: {data} </error>")
            return {}, None

    def _fetch_last_scan_id(self, project_id):
        log.info(
            f"<info> Fetching latest scan id for project id: {project_id} </info>",
        )
        # Convert to RFC 3339 format
        endpoint = f"sast/scans/?scanStatus=Finished&projectId={project_id}&last=1"
        data = self._fetch_data(endpoint)
        if isinstance(data, list) and len(data) >0:
            scan = data[0]
            lang_opt = []
            langs = scan.get("scanState",{}).get("languageStateCollection",[])
            for lang in langs:
                lang_opt.append(lang.get("languageName"))
            self.lang_opt = lang_opt
            return data, [scan.get("id")]
        else:
            log.error(f"<error> There is unknown issue: {data} </error>")
            return [], []


    def data_formater(self, findings):
        formated_finding = []
        severity_map = {0:"INFO", 1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}
        query_ids = set()
        # Helper to clean HTML from resultDescription
        def clean_description(html_text):
            # Remove <style> tags and content
            html_text = re.sub(r'<style.*?>.*?</style>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
            # Remove "Similarity ID" span
            html_text = re.sub(r'<span[^>]*?>Similarity ID:.*?</span>', '', html_text, flags=re.IGNORECASE)
            # Remove all other HTML tags
            html_text = re.sub(r'<[^>]+>', '', html_text)
            # Decode HTML entities (e.g., &#39;, &nbsp;)
            html_text = html.unescape(html_text)
            # Normalize whitespace
            html_text = html_text.replace('\xa0', ' ')
            html_text = re.sub(r'\s+', ' ', html_text)
            return html_text.strip()

        for finding in findings:
            nodes = finding.get("nodes", [])
            first_node = nodes[0] if nodes else {}
            query_id =  finding.get("query", {}).get("queryId")
            sast_result = {
                "type": "sast",
                "id": finding.get("index"),
                "similarityId": str(finding.get("similarityHash")),
                "status": finding.get("status"),
                "state": finding.get("state"),
                "severity": severity_map.get(finding.get("severity")),
                "confidenceLevel": finding.get("confidenceLevel"),
                "created": finding.get("date"),
                "firstFoundAt": finding.get("detectionDate"),
                "foundAt": finding.get("date"),
                "description": clean_description(finding.get("resultDescription", "")),
                "data": {
                    "queryId": query_id,
                    "queryName": finding.get("query", {}).get("name"),
                    "group": "Unknown",
                    "resultHash": finding.get("index"),
                    "languageName": "Unknown",
                    "nodes": [
                        {
                            "id": str(node.get("nodeId")),
                            "line": node.get("line"),
                            "name": node.get("shortName"),
                            "column": node.get("column"),
                            "length": node.get("length"),
                            "nodeID": node.get("nodeId"),
                            "fileName": node.get("fileName"),
                            "fullName": node.get("fullName"),
                            "methodLine": node.get("methodLine")
                        }
                        for node in nodes
                    ]
                },
                "comments": {},
                "vulnerabilityDetails": {
                    "cweId": finding.get("query", {}).get("cwe"),
                    "compliances": finding.get("query", {}).get("categories", "").split("; ")
                }
            }

            formated_finding.append(sast_result)
            query_ids.add(query_id)
        return formated_finding, query_ids

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
        endpoint = f"sast/results/?limit={limit}&offset={offset}&scanId={scan_id}"
        data = self._fetch_data(endpoint)
        if isinstance(data, dict):
            total_count = data.get("totalCount")
            if total_count is not None:
                all_result["finding"] = data.get("results", [])
                offset = math.ceil(total_count / limit)
            for count in range(1, offset):
                endpoint = f"sast/results/?limit={limit}&offset={count}&scanId={scan_id}"
                data = self._fetch_data(endpoint)
                if isinstance(data, dict) and data.get("results"):
                    all_result["finding"] += data.get("results", [])

            all_result["finding"], query_ids = self.data_formater(all_result["finding"])

            all_result["query_desc"] = self._get_sast_query_detail(query_ids)
            return all_result


    def _parse_html_to_dict(self, query_id, html_content):
        soup = BeautifulSoup(html_content, "html.parser")

        def get_section_text(title):
            tag = soup.find('p', string=re.compile(re.escape(title), re.IGNORECASE))
            if tag:
                next_el = tag.find_next("pre")
                if next_el:
                    return html.unescape(next_el.get_text(strip=True, separator="\n"))
            return ""

        def get_code_samples():
            samples = []
            current_language = None
            current_title = None

            for tag in soup.find_all(['p', 'pre']):
                if tag.name == 'p' and "subtitle" in tag.get("class", []):
                    text = tag.get_text(strip=True)
                    if text.upper() in self.lang_opt:
                        current_language = text.upper()
                    else:
                        current_title = text
                elif tag.name == 'pre' and current_language:
                    code = html.unescape(tag.get_text(strip=True))
                    samples.append({
                        "progLanguage": current_language,
                        "code": code,
                        "title": current_title
                    })
                    current_title = None  # Reset title after using it
            return samples

        # Extract title from main heading
        main_title = soup.find('p', class_='doctitle')
        query_name = main_title.get_text(strip=True) if main_title else "UnknownQuery"

        result = {
            "queryId": query_id,
            "queryName": query_name,
            "risk": get_section_text("What might happen"),
            "cause": get_section_text("How does it happen"),
            "generalRecommendations": get_section_text("How to avoid it"),
            "samples": get_code_samples()
        }

        return result

    def _get_sast_query_detail(self, query_ids):
        log.info(f"<info> Fetching data for query_description </info>")
        query_description = {}
        for query_id in query_ids:
            endpoint = f"queries/{query_id}/cxDescription"
            data = self._fetch_data(endpoint, flag = False)
            if data:
                query_description[query_id] = self._parse_html_to_dict(query_id, data)
            else:
                query_description[query_id] = {}
        return query_description

    def run(self):
        self.bearer_token = self._get_checkmarx_bearer_token()
        if not self.bearer_token:
            log.error("Failed to retrieve Checkmarx bearer token.")
            return
        for project in self.env["PROJECT_NAMES"]:
            data, project_id = self._fetch_checkmarx_projects(project=project)
            if not project_id:
                log.warning(f"Project ID not found for {project}. Skipping.")
                continue
            scan_info, scan_ids  = self._fetch_last_scan_id(
                project_id,
            )
            if not scan_ids:
                log.warning(f"No scans found for project '{project}'")
                continue

            data["scan"] = scan_info
            data["result"] = [self._get_result(scan_id) for scan_id in scan_ids]
            try:
                time_suffix = str(time.time())
                issues_file = os.path.join(SCANNED_FILE_DIR, f"CHECKMARX-CX-{time_suffix}.json")
                with open(issues_file, "w") as f:
                    json.dump(data, f, indent=2)
                log.info(f"Results written to {issues_file}")
                self.upload_results(issues_file)
                log.info(f"Results uploaded for project '{project}'.")
                ## remove the json file 
                if os.path.exists(issues_file):
                    os.remove(issues_file)
            except Exception as e:
                log.error(f"Error while saving or uploading results for {project}: {e}")


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

                url = f"{self.env["CSPM_BASE_URL"]}/api/v1/artifact/"
                headers={
                        "Tenant-Id": self.env["TENANT_ID"],
                        "Authorization": f"Bearer {self.env["ARTIFACT_TOKEN"]}"
                    }
                params={
                        "tenant_id": self.env["TENANT_ID"],
                        "data_type": "CX",
                        "save_to_s3": "false",
                        "label_id": self.env["LABEL"],
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
    "PROJECT_NAMES",
    "BASE_URL",
    "USER_NAME",
    "PASSWORD",
    "CSPM_BASE_URL",
    "LABEL",
    "TENANT_ID",
    "ARTIFACT_TOKEN"
]

OPTIONAL_ENV_DEFAULTS = {
    "SCOPE": "sast_rest_api",
    "GRANT_TYPE": "password",
    "CLIENT_ID": "resource_owner_client",
    "CLIENT_SECRET": "014DF517-39D1-4453-B7B3-9930C563627C",
}

def get_env_config():
    missing = [key for key in REQUIRED_ENV_VARS if not os.environ.get(key)]
    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    config = {key: os.environ.get(key) for key in REQUIRED_ENV_VARS}

    # Parse PROJECT_NAMES as list from comma-separated string
    config["PROJECT_NAMES"] = [
        name.strip() for name in config["PROJECT_NAMES"].split(",") if name.strip()
    ]

    for key, default in OPTIONAL_ENV_DEFAULTS.items():
        config[key] = os.environ.get(key, default)

    return config


if __name__ == "__main__":
    env = get_env_config()
    cc = Checkmarx(env)
    cc.run()
