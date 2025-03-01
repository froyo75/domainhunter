#!/usr/bin/env python

## Title:       domainhunter.py
## Author:      @joevest and @andrewchiles
## Description: Checks expired domains, reputation/categorization, and Archive.org history to determine
##              good candidates for phishing and C2 domain names
## Updated: Updated Trellix (McAfee) Web Gateway (Cloud) reputation checking + Fixed Bluecoat + CISCO Talos: @froyo75
# If the expected response format from a provider changes, use the traceback module to get a full stack trace without removing try/catch blocks
#import traceback
#traceback.print_exc()

import time
import random
import argparse
import json
import base64
import os
import sys
from urllib.parse import urlparse
import getpass

####FIX CISCO TALOS+BLUECOAT######################
import re
import html
from bs4 import BeautifulSoup
from seleniumbase import SB
jitter = 1
######################################

__version__ = "20210108"

## Functions

####FIX CISCO TALOS###################################################################################################################################################
def checkTalos(domain):
    """Retrieve CISCO Talos Infos using SeleniumBase"""
    with SB(uc=True, headed=True, xvfb=False, incognito=True, ad_block=True, browser='chrome', locale_code="en") as sb:
        try:
            url = f"https://talosintelligence.com/reputation_center/lookup?search={domain}"
            print("[*] Retrieving infos from Cisco Talos...")
            
            timeout = random.randrange(delay, delay + jitter)
            # Open URL
            sb.activate_cdp_mode(url)
            sb.sleep(timeout)
            
            # Get page content
            response = sb.get_page_source()
            
            # Check for Cloudflare protection
            if "DDoS protection by" in response:
                print("\n[-] Error retrieving Talos reputation! => DDoS protection by Cloudflare "
                      "(Please try to increase the delay to bypass the bot mitigation system!)")
                return "error"

            # Initialize default values
            web_reputation = "Unknown"
            email_reputation = "Unknown"
            added_blocklist = "Unknown"
            category = "Uncategorized"

            # Parse the response
            soup = BeautifulSoup(response, "html.parser")
            
            # Find reputation and blocklist information
            for span in soup.findAll("span", {"class": ["email-rep-label details-rep--", "new-legacy-label", "tl-bl"]}):
                class_names = span['class']
                if "email-rep-label" in class_names and span.text != '-':
                    email_reputation = span.text
                if "new-legacy-label" in class_names:
                    web_reputation = span.text
                if "tl-bl" in class_names:
                    added_blocklist = span.text

            # Find category information
            category_elem = soup.find("td", {"class": "content-category"})
            if category_elem:
                category = category_elem.text

            if category == "Uncategorized":
                result = "Uncategorized"
            else:
                result = (f'{category.strip()}, Email Reputation: {email_reputation} / '
                       f'Web Reputation: {web_reputation} / '
                       f'Added to block list: {added_blocklist}')
            return result

        except Exception as e:
            print(f"[-] Error retrieving Talos information: {str(e)}")
            return "error"
###############################################################################################################################################################################

def doSleep(timing):
    """Add nmap like random sleep interval for multiple requests"""

    if timing == 0:
        time.sleep(random.randrange(90,120))
    elif timing == 1:
        time.sleep(random.randrange(60,90))
    elif timing == 2:
        time.sleep(random.randrange(30,60))
    elif timing == 3:
        time.sleep(random.randrange(10,20))
    elif timing == 4:
        time.sleep(random.randrange(5,10))
    # There's no elif timing == 5 here because we don't want to sleep for -t 5

def checkUmbrella(domain):
    """Umbrella Domain reputation service"""

    try:
        url = 'https://investigate.api.umbrella.com/domains/categorization/?showLabels'
        postData = [domain]

        headers = {
            'User-Agent':useragent,
            'Content-Type':'application/json; charset=UTF-8',
            'Authorization': 'Bearer {}'.format(umbrella_apikey)
        }

        print('[*] Umbrella: {}'.format(domain))
        
        response = s.post(url,headers=headers,json=postData,verify=False,proxies=proxies)
        responseJSON = json.loads(response.text)
        if len(responseJSON[domain]['content_categories']) > 0:
            return responseJSON[domain]['content_categories'][0]
        else:
            return 'Uncategorized'

    except Exception as e:
        print('[-] Error retrieving Umbrella reputation! {0}'.format(e))
        return "error"

####FIX BLUECOAT###################################################################################################################################################
def checkBluecoat(domain):
    """Retrieve Symantec Bluecoat info using SeleniumBase"""
    with SB(uc=True, headed=True, xvfb=False, incognito=True, ad_block=True, browser='chrome', locale_code="en") as sb:
        try:
            url = "https://sitereview.bluecoat.com/#/lookup-result/" + domain
            print("[*] Checking Bluecoat for:", domain)
            
            timeout = random.randrange(delay, delay + jitter)
            # Open URL and Handle Turnstile
            sb.activate_cdp_mode(url)
            sb.sleep(timeout)
            sb.uc_gui_click_captcha("ngx-turnstile")
            sb.sleep(timeout)

            # Get page content
            content = sb.get_page_source()
            if not content:
                return "[-] Failed to get content"

            # Extract category using regex
            category_pattern = r'<span class="clickable-category">(.*?)</span>'
            matches = re.findall(category_pattern, content)
            
            # Extract rating date
            date_pattern = r'Last Time Rated/Reviewed: ([^<]+)'
            date_matches = re.findall(date_pattern, content)
            
            category = "Uncategorized"
            rating_date = "Unknown"
            
            if matches:
                category = matches[0].strip()
                print(f"[+] Found category: {category}")
                
                # Check if it's a high-profile URL
                if 'high-profile URL' in content and 'cannot be changed via Site Review' in content:
                    category += " (High Profile)"
            if date_matches:
                # Decode HTML entities and clean up the date string
                rating_date = html.unescape(date_matches[0].strip())
                print(f"[+] Last rated: {rating_date}")
                
            # Combine category and date
            result = f"{category} (Last rated: {rating_date})"
            return result

        except Exception as e:
            return f"[-] Bluecoat error: {str(e)}"  
###############################################################################################################################################################################

def checkMcAfeeWG(domain):
    """Trellix Web Gateway Domain Reputation"""
   
    try:
        print('[*] Trellix (McAfee) Web Gateway (Cloud): {}'.format(domain))

        # HTTP Session container, used to manage cookies, session tokens and other session information
        s = requests.Session()

        headers = {
                'User-Agent':useragent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Referer':'https://trustedsource.org/'
                }  

        # Establish our session information
        response = s.get("https://trustedsource.org",headers=headers,verify=False,proxies=proxies)
        
        # Pull the hidden attributes from the response
        soup = BeautifulSoup(response.text,"html.parser")
        hidden_tags = soup.find_all("input",  {"type": "hidden"})
        for tag in hidden_tags:
            if tag['name'] == 'sid':
                sid = tag['value']
            elif tag['name'] == 'e':
                e = tag['value']
            elif tag['name'] == 'c':
                c = tag['value']
            elif tag['name'] == 'p':
                p = tag['value']

        # Retrieve the categorization infos 
        multipart_form_data = {
            'sid': (None, sid),
            'e': (None, e),
            'c': (None, c),
            'p': (None, p),
            'action': (None, 'checksingle'),
            'product': (None, '14-ts'),
            'url': (None, domain)
        }

        response = s.post('https://trustedsource.org/en/feedback/url',headers=headers,files=multipart_form_data,verify=False,proxies=proxies)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text,"html.parser")
            for table in soup.findAll("table", {"class": ["result-table"]}):
                datas = table.find_all('td')
                if "not valid" in datas[2].text:
                    result = 'Uncategorized'
                else:
                    status = datas[2].text
                    category = (datas[3].text[1:]).strip().replace('-',' -')
                    web_reputation = datas[4].text
                    if category:
                        result = '{0}, Status: {1}, Web Reputation: {2}'.format(category,status,web_reputation)
                    else:
                        result = 'Uncategorized'
            return result
        else:
            raise Exception

    except Exception as e:
        print('[-] Error retrieving Trellix (McAfee) Web Gateway Domain Reputation!')
        return "error"

def checkIBMXForce(domain):
    """IBM XForce Domain Reputation"""

    try: 
        url = 'https://exchange.xforce.ibmcloud.com/url/{}'.format(domain)
        headers = {'User-Agent':useragent,
                    'Accept':'application/json, text/plain, */*',
                    'x-ui':'XFE',
                    'Origin':url,
                    'Referer':url}

        print('[*] IBM xForce: {}'.format(domain))

        url = 'https://api.xforce.ibmcloud.com/url/{}'.format(domain)
        response = s.get(url,headers=headers,verify=False,proxies=proxies)

        responseJSON = json.loads(response.text)

        if 'error' in responseJSON:
            result = responseJSON['error']

        elif not responseJSON['result']['cats']:
            result = 'Uncategorized'
	
	## TO-DO - Add noticed when "intrusion" category is returned. This is indication of rate limit / brute-force protection hit on the endpoint        

        else:
            categories = ''
            # Parse all dictionary keys and append to single string to get Category names
            for key in responseJSON['result']['cats']:
                categories += '{0}, '.format(str(key))

            result = '{0}(Score: {1})'.format(categories,str(responseJSON['result']['score']))

        return result

    except Exception as e:
        print('[-] Error retrieving IBM-Xforce reputation! {0}'.format(e))
        return "error"


def checkMXToolbox(domain):
    """ Checks the MXToolbox service for Google SafeBrowsing and PhishTank information. Currently broken"""
    url = 'https://mxtoolbox.com/Public/Tools/BrandReputation.aspx'
    headers = {'User-Agent':useragent,
            'Origin':url,
            'Referer':url}  

    print('[*] Google SafeBrowsing and PhishTank: {}'.format(domain))
    
    try:
        response = s.get(url=url, headers=headers,proxies=proxies,verify=False)
        
        soup = BeautifulSoup(response.content,'lxml')

        viewstate = soup.select('input[name=__VIEWSTATE]')[0]['value']
        viewstategenerator = soup.select('input[name=__VIEWSTATEGENERATOR]')[0]['value']
        eventvalidation = soup.select('input[name=__EVENTVALIDATION]')[0]['value']

        data = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": viewstate,
        "__VIEWSTATEGENERATOR": viewstategenerator,
        "__EVENTVALIDATION": eventvalidation,
        "ctl00$ContentPlaceHolder1$brandReputationUrl": domain,
        "ctl00$ContentPlaceHolder1$brandReputationDoLookup": "Brand Reputation Lookup",
        "ctl00$ucSignIn$hfRegCode": 'missing',
        "ctl00$ucSignIn$hfRedirectSignUp": '/Public/Tools/BrandReputation.aspx',
        "ctl00$ucSignIn$hfRedirectLogin": '',
        "ctl00$ucSignIn$txtEmailAddress": '',
        "ctl00$ucSignIn$cbNewAccount": 'cbNewAccount',
        "ctl00$ucSignIn$txtFullName": '',
        "ctl00$ucSignIn$txtModalNewPassword": '',
        "ctl00$ucSignIn$txtPhone": '',
        "ctl00$ucSignIn$txtCompanyName": '',
        "ctl00$ucSignIn$drpTitle": '',
        "ctl00$ucSignIn$txtTitleName": '',
        "ctl00$ucSignIn$txtModalPassword": ''
        }
          
        response = s.post(url=url, headers=headers, data=data,proxies=proxies,verify=False)

        soup = BeautifulSoup(response.content,'lxml')

        result = ''
        if soup.select('div[id=ctl00_ContentPlaceHolder1_noIssuesFound]'):
            result = 'No issues found'
            return result
        else:
            if soup.select('div[id=ctl00_ContentPlaceHolder1_googleSafeBrowsingIssuesFound]'):
                result = 'Google SafeBrowsing Issues Found. '
        
            if soup.select('div[id=ctl00_ContentPlaceHolder1_phishTankIssuesFound]'):
                result += 'PhishTank Issues Found'
            return result

    except Exception as e:
        print('[-] Error retrieving Google SafeBrowsing and PhishTank reputation!')
        return "error"

def downloadMalwareDomains(malwaredomainsURL):
    """Downloads a current list of known malicious domains"""

    url = malwaredomainsURL
    response = s.get(url=url,headers=headers,verify=False,proxies=proxies)
    responseText = response.text
    if response.status_code == 200:
        return responseText
    else:
        print("[-] Error reaching:{}  Status: {}").format(url, response.status_code)

def checkDomain(domain):
    """Executes various domain reputation checks included in the project"""

    print('[*] Fetching domain reputation for: {}'.format(domain))

    if domain in maldomainsList:
        print("[!] {}: Identified as known malware domain (malwaredomains.com)".format(domain))
      
    bluecoat = checkBluecoat(domain)
    print("[+] {}: {}".format(domain, bluecoat))
    
    ibmxforce = checkIBMXForce(domain)
    print("[+] {}: {}".format(domain, ibmxforce))

    mcafeewg = checkMcAfeeWG(domain)
    print("[+] {}: {}".format(domain, mcafeewg))

    ciscotalos = checkTalos(domain)
    print("[+] {}: {}".format(domain, ciscotalos))

    #This service has completely changed, removing for now
    #mxtoolbox = checkMXToolbox(domain)
    #print("[+] {}: {}".format(domain, mxtoolbox))
    mxtoolbox = "-"

    umbrella = "not available"
    if len(umbrella_apikey):
        umbrella = checkUmbrella(domain)
        print("[+] {}: {}".format(domain, umbrella))

    print("")
    
    results = [domain,bluecoat,ibmxforce,mcafeewg,ciscotalos,umbrella,mxtoolbox]
    return results

def solveCaptcha(url,session):  
    """Downloads CAPTCHA image and saves to current directory for OCR with tesseract
    Returns CAPTCHA string or False if error occured
    """
    
    jpeg = 'captcha.jpg'
    
    try:
        response = session.get(url=url,headers=headers,verify=False, stream=True,proxies=proxies)
        if response.status_code == 200:
            with open(jpeg, 'wb') as f:
                response.raw.decode_content = True
                shutil.copyfileobj(response.raw, f)
        else:
            print('[-] Error downloading CAPTCHA file!')
            return False

        # Perform basic OCR without additional image enhancement
        text = pytesseract.image_to_string(Image.open(jpeg))
        text = text.replace(" ", "")
        
        # Remove CAPTCHA file
        try:
            os.remove(jpeg)
        except OSError:
            pass

        return text

    except Exception as e:
        print("[-] Error solving CAPTCHA - {0}".format(e))
        
        return False

def drawTable(header,data):
    """Generates a text based table for printing to the console"""
    data.insert(0,header)
    t = Texttable(max_width=maxwidth)
    t.add_rows(data)
    t.header(header)
    
    return(t.draw())

def loginExpiredDomains():
    """Login to the ExpiredDomains site with supplied credentials"""

    data = "login=%s&password=%s&redirect_2_url=/" % (username, password)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    r = s.post(expireddomainHost + "/login/", headers=headers, data=data, proxies=None, verify=False, allow_redirects=False)
    cookies = s.cookies.get_dict()

    if "location" in r.headers:
        if "/login/" in r.headers["location"]:
            print("[!] Login failed")
            sys.exit()

    if "ExpiredDomainssessid" in cookies:
        print("[+] Login successful.  ExpiredDomainssessid: %s" % (cookies["ExpiredDomainssessid"]))
    else:
        print("[!] Login failed")
        sys.exit()

def getIndex(cells, index):
        if cells[index].find("a") == None:
            return cells[index].text.strip()
        
        return cells[index].find("a").text.strip()

## MAIN
if __name__ == "__main__":


    parser = argparse.ArgumentParser(
        description='Finds expired domains, domain categorization, and Archive.org history to determine good candidates for C2 and phishing domains',
        epilog = '''
Examples:
./domainhunter.py -k apples -c --ocr -t5
./domainhunter.py --check --ocr -t3
./domainhunter.py --single mydomain.com
./domainhunter.py --keyword tech --check --ocr --timing 5 --alexa
./domainhunter.py --filename domains.list --ocr --timing 5''',
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('-a','--alexa', help='Filter results to Alexa listings', required=False, default=0, action='store_const', const=1)
    parser.add_argument('-k','--keyword', help='Keyword used to refine search results', required=False, default=False, type=str, dest='keyword')
    parser.add_argument('-c','--check', help='Perform domain reputation checks', required=False, default=False, action='store_true', dest='check')
    parser.add_argument('-f','--filename', help='Specify input file of line delimited domain names to check', required=False, default=False, type=str, dest='filename')
    parser.add_argument('--ocr', help='Perform OCR on CAPTCHAs when challenged', required=False, default=False, action='store_true')
    parser.add_argument('-r','--maxresults', help='Number of results to return when querying latest expired/deleted domains', required=False, default=100, type=int, dest='maxresults')
    parser.add_argument('-s','--single', help='Performs detailed reputation checks against a single domain name/IP.', required=False, default=False, dest='single')
    parser.add_argument('-t','--timing', help='Modifies request timing to avoid CAPTCHAs. Slowest(0) = 90-120 seconds, Default(3) = 10-20 seconds, Fastest(5) = no delay', required=False, default=3, type=int, choices=range(0,6), dest='timing')
    parser.add_argument('-w','--maxwidth', help='Width of text table', required=False, default=400, type=int, dest='maxwidth')
    parser.add_argument('-V','--version', action='version',version='%(prog)s {version}'.format(version=__version__))
    parser.add_argument("-P", "--proxy", required=False, default=None, help="proxy. ex https://127.0.0.1:8080")
    parser.add_argument("-u", "--username", required=False, default=None, type=str, help="username for expireddomains.net")
    parser.add_argument("-p", "--password", required=False, default=None, type=str, help="password for expireddomains.net")
    parser.add_argument("-o", "--output", required=False, default=None, type=str, help="output file path")
    parser.add_argument('-ks','--keyword-start', help='Keyword starts with used to refine search results', required=False, default="", type=str, dest='keyword_start')
    parser.add_argument('-ke','--keyword-end', help='Keyword ends with used to refine search results', required=False, default="", type=str, dest='keyword_end')
    parser.add_argument('-um','--umbrella-apikey', help='API Key for umbrella (paid)', required=False, default="", type=str, dest='umbrella_apikey')
    parser.add_argument('-d','--delay', help='Specify the delay (in seconds) to bypass DDoS antibot system (Distil / Imperva/ Datadadome / CloudFlare IUAM)', required=False, default=10, type=int)
    parser.add_argument('-q','--quiet', help='Surpress initial ASCII art and header', required=False, default=False, action='store_true', dest='quiet')
    args = parser.parse_args()

    # Load dependent modules
    try:
        import requests
        from bs4 import BeautifulSoup
        from texttable import Texttable
        
    except Exception as e:
        print("Expired Domains Reputation Check")
        print("[-] Missing basic dependencies: {}".format(str(e)))
        print("[*] Install required dependencies by running `pip3 install -r requirements.txt`")
        quit(0)

    # Load OCR related modules if --ocr flag is set since these can be difficult to get working
    if args.ocr:
        try:
            import pytesseract
            from PIL import Image
            import shutil
        except Exception as e:
            print("Expired Domains Reputation Check")
            print("[-] Missing OCR dependencies: {}".format(str(e)))
            print("[*] Install required Python dependencies by running: pip3 install -r requirements.txt")
            print("[*] Ubuntu\Debian - Install tesseract by running: apt-get install tesseract-ocr python3-imaging")
            print("[*] macOS - Install tesseract with homebrew by running: brew install tesseract")
            quit(0)
    
## Variables
    #######FIX CISCO TALOS######
    delay = args.delay
    ###########################

    username = args.username

    password = args.password

    proxy = args.proxy

    alexa = args.alexa

    keyword = args.keyword
    
    check = args.check

    filename = args.filename
    
    maxresults = args.maxresults
    
    single = args.single

    timing = args.timing

    maxwidth = args.maxwidth
    
    ocr = args.ocr

    output = args.output

    keyword_start = args.keyword_start

    keyword_end = args.keyword_end

    umbrella_apikey = args.umbrella_apikey

    malwaredomainsURL = 'https://gitlab.com/gerowen/old-malware-domains-ad-list/-/raw/master/malwaredomainslist.txt'
    expireddomainsqueryURL = 'https://www.expireddomains.net/domain-name-search'
    expireddomainHost = "https://member.expireddomains.net"

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    useragent = 'Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; WOW64; Trident/6.0)'

    headers = {'User-Agent':useragent}

    proxies = {}

    requests.packages.urllib3.disable_warnings()
 
    # HTTP Session container, used to manage cookies, session tokens and other session information
    s = requests.Session()

    if(args.proxy != None):
        proxy_parts = urlparse(args.proxy)
        proxies["http"] = "http://%s" % (proxy_parts.netloc)
        proxies["https"] = "http://%s" % (proxy_parts.netloc)
    s.proxies = proxies
    title = '''
 ____   ___  __  __    _    ___ _   _   _   _ _   _ _   _ _____ _____ ____  
|  _ \ / _ \|  \/  |  / \  |_ _| \ | | | | | | | | | \ | |_   _| ____|  _ \ 
| | | | | | | |\/| | / _ \  | ||  \| | | |_| | | | |  \| | | | |  _| | |_) |
| |_| | |_| | |  | |/ ___ \ | || |\  | |  _  | |_| | |\  | | | | |___|  _ < 
|____/ \___/|_|  |_/_/   \_\___|_| \_| |_| |_|\___/|_| \_| |_| |_____|_| \_\ '''

    # Print header
    if not (args.quiet):
        print(title)
        print('''\nExpired Domains Reputation Checker
Authors: @joevest and @andrewchiles
Updated by: @froyo75 (Updated Trellix (McAfee) Web Gateway (Cloud) reputation checking & Fixed Bluecoat + CISCO TALOS)\n
DISCLAIMER: This is for educational purposes only!
It is designed to promote education and the improvement of computer/cyber security.  
The authors or employers are not liable for any illegal act or misuse performed by any user of this tool.
If you plan to use this content for illegal purpose, don't.  Have a nice day :)\n''')

    # Download known malware domains
    # print('[*] Downloading malware domain list from {}\n'.format(malwaredomainsURL))
    
    maldomains = downloadMalwareDomains(malwaredomainsURL)
    maldomainsList = maldomains.split("\n")

    # Retrieve reputation for a single choosen domain (Quick Mode)
    if single:
        checkDomain(single)
        exit(0)

    # Perform detailed domain reputation checks against input file, print table, and quit. This does not generate an HTML report
    if filename:
        # Initialize our list with an empty row for the header
        data = []
        try:
            with open(filename, 'r') as domainsList:
                for line in domainsList.read().splitlines():
                    data.append(checkDomain(line))
                    doSleep(timing)

                # Print results table
                #header = ['Domain', 'BlueCoat', 'IBM X-Force', 'Trellix (McAfee) Web Gateway (Cloud)', 'Cisco Talos', 'Umbrella']
                header = ['Domain', 'BlueCoat', 'IBM X-Force', 'Trellix (McAfee) Web Gateway (Cloud)', 'Cisco Talos', 'Umbrella', 'MXToolbox']
                print(drawTable(header,data))

        except KeyboardInterrupt:
            print('Caught keyboard interrupt. Exiting!')
            exit(0)
        except Exception as e:
            print('[-] Error: {}'.format(e))
            exit(1)
        exit(0)

    # Lists for our ExpiredDomains results
    domain_list = []
    data = []

    # Generate list of URLs to query for expired/deleted domains
    urls = []
    if username == None or username == "":
        print('[-] Error: ExpiredDomains.net requires a username! Use the --username parameter')
        exit(1)
    if args.password == None or args.password == "":
        password = getpass.getpass("expireddomains.net Password: ")

    loginExpiredDomains()
    
    m = 200
    if maxresults < m:
        m = maxresults

    for i in range (0,(maxresults),m):
        k=""
        if keyword:
            k=keyword
        urls.append('{}/domains/combinedexpired/?fwhois=22&fadult=1&start={}&ftlds[]=2&ftlds[]=3&ftlds[]=4&flimit={}&fdomain={}&fdomainstart={}&fdomainend={}&falexa={}'.format(expireddomainHost,i,m,k,keyword_start,keyword_end,alexa))

    max_reached = False
    for url in urls:

        print("[*] {}".format(url))
        domainrequest = s.get(url,headers=headers,verify=False,proxies=proxies)
        domains = domainrequest.text
   
        # Turn the HTML into a Beautiful Soup object
        soup = BeautifulSoup(domains, 'html.parser')

        try:
            table = soup.find_all("table", class_="base1")
            tbody = table[0].select("tbody tr")
            

            for row in tbody:
                # Alternative way to extract domain name
                # domain = row.find('td').find('a').text

                cells = row.findAll("td")
                
                if len(cells) == 1:
                    max_reached = True
                    break # exit if max rows reached

                if len(cells) >= 1:
                    c0 = getIndex(cells, 0).lower()   # domain
                    c1 = getIndex(cells, 3)   # bl
                    c2 = getIndex(cells, 4)   # domainpop
                    c3 = getIndex(cells, 5)   # birth
                    c4 = getIndex(cells, 7)   # Archive.org entries
                    c5 = getIndex(cells, 8)   # Alexa
                    c6 = getIndex(cells, 10)  # Dmoz.org
                    c7 = getIndex(cells, 12)  # status com
                    c8 = getIndex(cells, 13)  # status net
                    c9 = getIndex(cells, 14)  # status org
                    c10 = getIndex(cells, 17)  # status de
                    c11 = getIndex(cells, 11)  # TLDs
                    c12 = getIndex(cells, 19)  # RDT
                    c13 = ""                    # List
                    c14 = getIndex(cells, 22)  # Status
                    c15 = ""                    # links

                    # create available TLD list
                    available = ''
                    if c7 == "available":
                        available += ".com "

                    if c8 == "available":
                        available += ".net "

                    if c9 == "available":
                        available += ".org "

                    if c10 == "available":
                        available += ".de "
                    
                    # Only grab status for keyword searches since it doesn't exist otherwise
                    status = ""
                    if keyword:
                        status = c14

                    if keyword:
                        # Only add Expired, not Pending, Backorder, etc
                        # "expired" isn't returned any more, I changed it to "available"
                        if c14 == "available": # I'm not sure about this, seems like "expired" isn't an option anymore.  expireddomains.net might not support this any more.
                            # Append parsed domain data to list if it matches our criteria (.com|.net|.org and not a known malware domain)
                            if (c0.lower().endswith(".com") or c0.lower().endswith(".net") or c0.lower().endswith(".org")) and (c0 not in maldomainsList):
                                domain_list.append([c0,c3,c4,available,status])
                        
                    # Non-keyword search table format is slightly different
                    else:
                        # Append original parsed domain data to list if it matches our criteria (.com|.net|.org and not a known malware domain)
                        if (c0.lower().endswith(".com") or c0.lower().endswith(".net") or c0.lower().endswith(".org")) and (c0 not in maldomainsList):
                            domain_list.append([c0,c3,c4,available,status]) 
            if max_reached:
                print("[*] All records returned")
                break

        except Exception as e: 
            print("[!] Error: ", e)
            pass

        # Add additional sleep on requests to ExpiredDomains.net to avoid errors
        time.sleep(5)

    # Check for valid list results before continuing
    if len(domain_list) == 0:
        print("[-] No domain results found or none are currently available for purchase!")
        exit(0)
    else:
        domain_list_unique = []
        [domain_list_unique.append(item) for item in domain_list if item not in domain_list_unique]

        # Print number of domains to perform reputation checks against
        if check:
            print("\n[*] Performing reputation checks for {} domains".format(len(domain_list_unique)))
            print("")

        for domain_entry in domain_list_unique:
            domain = domain_entry[0]
            birthdate = domain_entry[1]
            archiveentries = domain_entry[2]
            availabletlds = domain_entry[3]
            status = domain_entry[4]
            bluecoat = '-'
            ibmxforce = '-'
            mcafeewg = '-'
            ciscotalos = '-'
            umbrella = '-'

            # Perform domain reputation checks
            if check:
                unwantedResults = ['Uncategorized','error','Not found.','Spam','Spam URLs','Pornography','badurl','Suspicious','Malicious Sources/Malnets','captcha','Phishing','Placeholders']
                
                bluecoat = checkBluecoat(domain)
                if bluecoat not in unwantedResults:
                    print("[+] Bluecoat - {}: {}".format(domain, bluecoat))
                
                ibmxforce = checkIBMXForce(domain)
                if ibmxforce not in unwantedResults:
                    print("[+] IBM XForce - {}: {}".format(domain, ibmxforce))
                
                mcafeewg = checkMcAfeeWG(domain)
                if mcafeewg not in unwantedResults:
                    print("[+] Trellix (McAfee) Web Gateway (Cloud) {}: {}".format(domain, mcafeewg))

                ciscotalos = checkTalos(domain)
                if ciscotalos not in unwantedResults:
                    print("[+] Cisco Talos {}: {}".format(domain, ciscotalos))

                if len(umbrella_apikey):
                    umbrella = checkUmbrella(domain)
                    if umbrella not in unwantedResults:
                        print("[+] Umbrella {}: {}".format(domain, umbrella))

                print("")
                # Sleep to avoid captchas
                doSleep(timing)

            # Append entry to new list with reputation if at least one service reports reputation
            if not ((bluecoat in ('Uncategorized','badurl','Suspicious','Malicious Sources/Malnets','captcha','Phishing','Placeholders','Spam','error')) \
                and (ibmxforce in ('Not found.','error')) and (mcafeewg in ('Uncategorized','error')) and (ciscotalos in ('Uncategorized','error')) and (umbrella in ('Uncategorized','None'))):
                
                data.append([domain,birthdate,archiveentries,availabletlds,status,bluecoat,ibmxforce,mcafeewg,ciscotalos,umbrella])

    # Sort domain list by column 2 (Birth Year)
    sortedDomains = sorted(data, key=lambda x: x[1], reverse=True) 

    if check:
        if len(sortedDomains) == 0:
            print("[-] No domains discovered with a desireable categorization!")
            exit(0)
        else:
            print("[*] {} of {} domains discovered with a potentially desireable categorization!".format(len(sortedDomains),len(domain_list)))

    # Build HTML Table
    html = ''
    htmlHeader = '<html><head><title>Expired Domain List</title></head>'
    htmlBody = '<body><p>The following available domains report was generated at {}</p>'.format(timestamp)
    htmlTableHeader = '''
                
                 <table border="1" align="center">
                    <th>Domain</th>
                    <th>Birth</th>
                    <th>Entries</th>
                    <th>TLDs Available</th>
                    <th>Status</th>
                    <th>BlueCoat</th>
                    <th>IBM X-Force</th>
                    <th>Trellix (McAfee) Web Gateway (Cloud)<th>
                    <th>Cisco Talos</th>
                    <th>Umbrella</th>
                    <th>WatchGuard</th>
                    <th>Namecheap</th>
                    <th>Archive.org</th>
                 '''

    htmlTableBody = ''
    htmlTableFooter = '</table>'
    htmlFooter = '</body></html>'

    # Build HTML table contents
    for i in sortedDomains:
        htmlTableBody += '<tr>'
        htmlTableBody += '<td>{}</td>'.format(i[0]) # Domain
        htmlTableBody += '<td>{}</td>'.format(i[1]) # Birth
        htmlTableBody += '<td>{}</td>'.format(i[2]) # Entries
        htmlTableBody += '<td>{}</td>'.format(i[3]) # TLDs
        htmlTableBody += '<td>{}</td>'.format(i[4]) # Status

        htmlTableBody += '<td><a href="https://sitereview.bluecoat.com/" target="_blank">{}</a></td>'.format(i[5]) # Bluecoat
        htmlTableBody += '<td><a href="https://exchange.xforce.ibmcloud.com/url/{}" target="_blank">{}</a></td>'.format(i[0],i[6]) # IBM x-Force Categorization
        htmlTableBody += '<td><a href="https://trustedsource.org/en/feedback/url?action=checksingle&url=http%3A%2F%2F{}&product=14-ts" target="_blank">{}</a></td>'.format(i[0],i[7]) # Trellix (McAfee) Web Gateway (Cloud)
        htmlTableBody += '<td><a href="https://www.talosintelligence.com/reputation_center/lookup?search={}" target="_blank">{}</a></td>'.format(i[0],i[8]) # Cisco Talos
        htmlTableBody += '<td>{}</td>'.format(i[9]) # Cisco Umbrella
        htmlTableBody += '<td><a href="http://www.borderware.com/domain_lookup.php?ip={}" target="_blank">WatchGuard</a></td>'.format(i[0]) # Borderware WatchGuard
        htmlTableBody += '<td><a href="https://www.namecheap.com/domains/registration/results.aspx?domain={}" target="_blank">Namecheap</a></td>'.format(i[0]) # Namecheap
        htmlTableBody += '<td><a href="http://web.archive.org/web/*/{}" target="_blank">Archive.org</a></td>'.format(i[0]) # Archive.org
        htmlTableBody += '</tr>'

    html = htmlHeader + htmlBody + htmlTableHeader + htmlTableBody + htmlTableFooter + htmlFooter

    logfilename = "{}_domainreport.html".format(timestamp)
    if output != None:
        logfilename = output

    log = open(logfilename,'w')
    log.write(html)
    log.close

    print("\n[*] Search complete")
    print("[*] Log written to {}\n".format(logfilename))
    
    # Print Text Table
    header = ['Domain', 'Birth', '#', 'TLDs', 'Status', 'BlueCoat', 'IBM', 'Trellix (McAfee) Web Gateway (Cloud)', 'Cisco Talos', 'Umbrella']
    print(drawTable(header,sortedDomains))
