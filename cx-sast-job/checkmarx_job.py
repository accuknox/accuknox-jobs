
import html
import json
import logging
import math
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup
from requests.exceptions import SSLError

# Initialize logging
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SCANNED_FILE_DIR = os.environ.get("REPORT_PATH", "/app/data/")


class Checkmarx:
    def __init__(self, project_name, base_url, username, password, scope, grant_type, client_id, client_secret):
        self.project_name = project_name
        self.base_url = base_url
        self.username = username
        self.password = password
        self.scope = scope
        self.grant_type = grant_type
        self.client_id = client_id
        self.client_secret = client_secret
        self.bearer_token = ""

    MAX_RETRIES = 3  # Maximum retry attempts

    def _get_checkmarx_bearer_token(self):
        """
        Fetch authentication token for Checkmarx.
        """
        try:
            log.info(f"<info> Fetching bearer token ... </info>")

            payload = {
                "username": self.username,
                "password": self.password,
                "scope": self.scope ,
                "grant_type": self.grant_type or "password",
                "client_id": self.client_id or "resource_owner_client",
                "client_secret": self.client_secret or "014DF517-39D1-4453-B7B3-9930C563627C"
            }
            url = self.base_url+"/cxrestapi/auth/identity/connect/token"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
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

        url = f"{self.base_url}/cxrestapi/{endpoint}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.bearer_token}",
        }
        response = ""
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.get(url, headers=headers)
            except SSLError as ssl_err:
                response = requests.get(url, headers=headers, verify=False)
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
                message = response.json()
                if isinstance(message, dict) and 'messageCode' in message:
                    if message["messageCode"]==47826:
                        log.error(f"<error> Invalid Project name </error> ")
                        sys.exit(1)
                    if message["messageCode"]==25016:
                        log.error(f"<warning> Cx description not found for queryID : {endpoint} </warning> ")
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
            f"<info> Fetching latest scan id for project: {project_id} </info>",
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
        def clean_description(html):
            return re.sub('<[^<]+?>', '', html).replace('Similarity ID:', '').strip()

        for finding in findings:
            nodes = finding.get("nodes", [])
            first_node = nodes[0] if nodes else {}
            query_id =  finding.get("query", {}).get("queryId")
            sast_result = {
                "type": "sast",
                "id": finding.get("similarityHash"),
                "alternateId": finding.get("similarityHash"),
                "similarityId": str(finding.get("similarityHash", 0)),
                "status": finding.get("status"),
                "state": finding.get("state", 4),
                "severity": severity_map.get(finding.get("severity", 3), "LOW"),
                "confidenceLevel": finding.get("confidenceLevel", 0),
                "created": finding.get("date"),
                "firstFoundAt": finding.get("detectionDate"),
                "foundAt": finding.get("date"),
                "firstScanId": finding.get("deepLink", "").split("scanid=")[-1].split("&")[0] if "scanid=" in finding.get("deepLink", "") else "",
                "description": clean_description(finding.get("resultDescription", "")),
                "data": {
                    "queryId": query_id,
                    "queryName": finding.get("query", {}).get("name"),
                    "group": "Unknown",
                    "resultHash": finding.get("similarityHash"),
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
        if self.bearer_token:
            data, project_id = self._fetch_checkmarx_projects(project=self.project_name)
            if project_id:
                scan_info, scan_ids  = self._fetch_last_scan_id(
                    project_id,
                )
                data["scan"] = scan_info
                scan_result = []
                for scan_id in scan_ids:
                    scan_result.append(self._get_result(scan_id))
                data["result"] = scan_result

                # Write results to file
                time_suffix = str(time.time())
                issues_file = os.path.join(SCANNED_FILE_DIR, f"CHECKMARX-CX-{time_suffix}.json")
                with open(issues_file, "w") as f:
                    json.dump(data, f, indent=2)


if __name__ == "__main__":
    project_name = os.environ.get("PROJECT_NAME","AccuKnox Integration")
    base_url = os.environ.get("BASE_URL","https://partners9x.checkmarx.net")
    username = os.environ.get("USER_NAME")
    password = os.environ.get("PASSWARD")
    scope = os.environ.get("SCOPE", "sast_rest_api")
    grant_type = os.environ.get("GRANT_TYPE", "password")
    client_id = os.environ.get("CLIENT_ID", "resource_owner_client")
    client_secret = os.environ.get("CLIENT_SECRET", "014DF517-39D1-4453-B7B3-9930C563627C")

    missing_vars = []
    if not username:
        missing_vars.append("USER_NAME")
    if not project_name:
        missing_vars.append("PROJECT_NAME")
    if not base_url:
        missing_vars.append("BASE_URL")
    if not password:
        missing_vars.append("PASSWARD")

    if missing_vars:
        print(
            f"❌ Error: Missing required environment variable(s): {', '.join(missing_vars)}",
            file=sys.stderr,
        )
        sys.exit(1)
    cc = Checkmarx(project_name, base_url, username, password, scope, grant_type, client_id, client_secret)
    cc.run()
