import os
import re
import time
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException, TimeoutException, StaleElementReferenceException # Added StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains # Added ActionChains

# Default credentials
DEFAULT_CREDENTIALS = {
    "username": "YOUR USERNAME",
    "password": "YOUR PASSWORD"
}

def login(driver, credentials=None):
    """
    Logs into Mathspace using the provided credentials
    """
    if not credentials:
        credentials = DEFAULT_CREDENTIALS
        
    print("Logging into Mathspace...")
    
    # Wait for username field and enter username
    username_field = WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "#div_id_username input"))
    )
    username_field.send_keys(credentials["username"])
    
    # Click continue button
    continue_btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#submit-id-login"))
    )
    continue_btn.click()
    
    # Wait for password field and enter password
    password_field = WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "#div_id_password input"))
    )
    password_field.send_keys(credentials["password"])
    
    # Submit login form
    login_btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#submit-id-login"))
    )
    login_btn.click()
    
    # Wait for navigation to complete
    WebDriverWait(driver, 20).until(
        lambda d: "accounts/login" not in d.current_url
    )
    
    print("Login successful")
    return driver

def clean_question_text(text):
    """Clean question text to remove noise and formatting"""
    if not text:
        return ""
    
    # Initial cleaning
    cleaned = text
    
    # Remove promotional text
    cleaned = re.sub(r'Back to School Special:.+?Upgrade', '', cleaned, flags=re.DOTALL)
    
    # Remove section titles with numbering patterns
    cleaned = re.sub(r'\d+\.\d+\s+[A-Za-z]+ in [a-z]+ [a-z]+', '', cleaned)
    
    # Remove excessive numbering while preserving important question numbers
    cleaned = re.sub(r'^\s*\d+\s*\.\s*', '', cleaned)
    
    # Remove dollar signs that might interfere with math expressions
    cleaned = re.sub(r'\$+', '', cleaned)
    
    # Normalize whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Remove irrelevant UI elements and text
    cleaned = re.sub(r'Help.+', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'Submit.+', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'Toolbox.+?More', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'\|\s+', '', cleaned)
    cleaned = re.sub(r'True A False B.+', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'Milo can now speak.*$', '', cleaned, flags=re.MULTILINE)
    
    # Remove buttons and UI text
    cleaned = re.sub(r'Previous Step|Next Step|Show Steps|Hide Steps', '', cleaned)
    
    # Remove timestamps and navigation
    cleaned = re.sub(r'\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(:\d{2})?', '', cleaned)
    
    # Final whitespace cleanup
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    
    return cleaned

def calculate_expression(expression_str):
    """
    Attempts to calculate the result of a mathematical expression string.
    """
    if not expression_str:
        return "Error: Empty expression."
    try:
        # Replace common math symbols with Python-compatible operators
        calculable_expr = expression_str.replace('×', '*').replace('÷', '/')
        # Add other replacements if necessary, e.g., for different minus signs or symbols

        # Validate the expression to allow only numbers, basic operators, parentheses, and spaces
        # This is a basic safety measure before using eval()
        if not re.fullmatch(r"^[0-9+\-*/().\s]+$", calculable_expr):
            return f"Error: Expression '{expression_str}' contains invalid characters for calculation."

        # Evaluate the expression
        # pylint: disable=eval-used
        result = eval(calculable_expr)
        return result
    except ZeroDivisionError:
        return "Error: Division by zero."
    except SyntaxError:
        return f"Error: Invalid mathematical expression syntax for '{calculable_expr}'."
    except Exception as e:
        return f"Error: Could not evaluate expression '{expression_str}' - {str(e)}"

def detect_problem_id_from_url(url):
    """Extract problem ID from URL"""
    match = re.search(r'/Problem-(\d+)', url)
    if match:
        return match.group(1)
    return None

def extract_questions(driver):
    """
    Extract questions directly from problem header and subproblem divs in Mathspace,
    handling the special case of ordered mathquill-command-id spans
    """
    print("Extracting question text...")
    all_question_parts = []

    try:
        # 1. Find the main problem header
        try:
            problem_header_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'problemHeaderWrapper_')]")
            
            if problem_header_elements:
                main_problem_text = problem_header_elements[0].text.strip()
                if main_problem_text:
                    all_question_parts.append(("MAIN PROBLEM", main_problem_text))
                    print(f"Found main problem header: {main_problem_text[:50]}...")
                    print("\nEXTRACTED MAIN PROBLEM:")
                    print("======================")
                    print("-" * 60)
                    print(main_problem_text)
                    print("-" * 60)
        except WebDriverException as e_wd:
            print(f"WebDriverException while extracting problem header: {e_wd}")
            # If session is lost here, further operations will fail.
            # Consider returning early or re-raising if critical.
            # For now, we'll let it try subproblems but it will likely fail too.
        except Exception as e:
            print(f"Error extracting problem header: {e}")
        
        # 2. Find all subproblems with special handling of mathquill spans
        try:
            # Updated to match the correct class name
            subproblem_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'subproblemInstruction_')]")
            
            if subproblem_elements:
                print(f"Found {len(subproblem_elements)} subproblem elements")
                
                for i, subproblem in enumerate(subproblem_elements):
                    # CHANGED: Use the fallback text extraction as primary method
                    subproblem_text = subproblem.text.strip()
                    
                    # If the fallback text is good, use it directly
                    if subproblem_text and len(subproblem_text) > 5:
                        if not any(input_pattern in subproblem_text.lower() for input_pattern in [
                            "enter your", "type your answer", "insert", "input here"
                        ]):
                            all_question_parts.append((f"SUBPROBLEM {i+1}", subproblem_text))
                            
                            # Display each extracted subquestion
                            print(f"\nEXTRACTED SUBQUESTION {i+1}:")
                            print("=" * 60)
                            print("-" * 60)
                            print(subproblem_text)
                            print("-" * 60)
                            continue  # Go to next subproblem
                    
                    # Only if fallback didn't work, try the complex extraction with mathquill spans
                    # Look for the inner div with class xBQ2HyCNJoo33_Z_K6va if it exists
                    inner_divs = subproblem.find_elements(By.CSS_SELECTOR, "div.xBQ2HyCNJoo33_Z_K6va")
                    if inner_divs:
                        print(f"Using complex extraction for subproblem {i+1}")
                        
                        for inner_div in inner_divs:
                            # Extract paragraph text if available
                            paragraphs = inner_div.find_elements(By.CSS_SELECTOR, "p")
                            paragraph_texts = [p.text.strip() for p in paragraphs if p.text.strip()]
                            paragraph_content = " ".join(paragraph_texts)
                            
                            # Process math fields
                            math_fields = inner_div.find_elements(By.CSS_SELECTOR, ".mathField_1vyaj94, .mq-math-mode")
                            if math_fields:
                                for math_field in math_fields:
                                    # Look for root-block that contains the math content
                                    root_blocks = math_field.find_elements(By.CSS_SELECTOR, "span.mq-root-block")
                                    if root_blocks:
                                        # Find all spans with mathquill-command-id attributes
                                        command_spans = []
                                        try:
                                            # Use JavaScript to get all spans with the attribute
                                            command_spans = driver.execute_script("""
                                                const span = arguments[0];
                                                return Array.from(span.querySelectorAll('[mathquill-command-id]')).map(el => {
                                                    return {
                                                        id: parseInt(el.getAttribute('mathquill-command-id')), 
                                                        text: el.textContent
                                                    };
                                                });
                                            """, root_blocks[0])
                                        except Exception as e_js: # Catch JS execution error specifically
                                            print(f"Error extracting mathquill spans via JS: {e_js}")
                                        
                                        if command_spans:
                                            # Sort by command ID
                                            command_spans.sort(key=lambda x: x['id'])
                                            
                                            # Extract ordered text
                                            ordered_math_text = ''.join([span['text'] for span in command_spans])
                                            if ordered_math_text:
                                                # Combine paragraph content with math content
                                                combined_content = f"{paragraph_content} {ordered_math_text}".strip()
                                                
                                                if combined_content and not any(input_pattern in combined_content.lower() for input_pattern in [
                                                    "enter your", "type your answer", "insert", "input here"
                                                ]):
                                                    all_question_parts.append((f"SUBPROBLEM {i+1} (COMPLEX)", combined_content))
                                                    

                                                    # Display each extracted subquestion
                                                    print(f"\nEXTRACTED SUBQUESTION {i+1} (COMPLEX):")
                                                    print("=" * 60)
                                                    print("-" * 60)
                                                    print(combined_content)
                                                    print("-" * 60)
                                                    
                                                    break  # Found a good extraction
        except WebDriverException as e_wd:
            print(f"WebDriverException while extracting subproblems: {e_wd}")
        except Exception as e:
            print(f"Error extracting subproblems: {e}")
            traceback.print_exc()
        
        # Check iframes if nothing found in the main document
        if not all_question_parts:
            try:
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                for i, iframe_element in enumerate(iframes): # Renamed to avoid conflict
                    try:
                        print(f"Checking iframe {i+1}/{len(iframes)}")
                        driver.switch_to.frame(iframe_element)
                        
                        # Look for problem header in iframe
                        header_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'problemHeaderWrapper_')]")
                        if header_elements:
                            header_text = header_elements[0].text.strip()
                            if header_text:
                                all_question_parts.append(("MAIN PROBLEM (IFRAME)", header_text))
                                print("\nEXTRACTED MAIN PROBLEM (IFRAME):")
                                print("==============================")
                                print("-" * 60)
                                print(header_text)
                                print("-" * 60)
                        
                        # Look for subproblems in iframe with the same special handling
                        sub_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'subproblem_')]")
                        print(f"Found {len(sub_elements)} subproblem elements in iframe")
                        
                        for j, sub in enumerate(sub_elements):
                            # First try text extraction
                            sub_text = sub.text.strip()
                            
                            # Try the special structure
                            prefix_spans = sub.find_elements(By.CSS_SELECTOR, "span.prefix")
                            if prefix_spans:
                                for prefix_span in prefix_spans:
                                    root_blocks = prefix_span.find_elements(By.CSS_SELECTOR, "span.mq-root-block")
                                    if root_blocks:
                                        command_spans = []
                                        try:
                                            command_spans = driver.execute_script("""
                                                const span = arguments[0];
                                                return Array.from(span.querySelectorAll('span[mathquill-command-id]')).map(el => {
                                                    return {
                                                        id: parseInt(el.getAttribute('mathquill-command-id')), 
                                                        text: el.textContent
                                                    };
                                                });
                                            """, root_blocks[0])
                                        except: # General exception for JS part
                                            pass
                                        
                                        if command_spans:
                                            command_spans.sort(key=lambda x: x['id'])
                                            ordered_math_text = ''.join([span['text'] for span in command_spans])
                                            if ordered_math_text:
                                                prefix_text = prefix_span.text.replace(ordered_math_text, '').strip()
                                                math_content = f"{prefix_text} {ordered_math_text}".strip()
                                                

                                                if math_content and not any(input_pattern in math_content.lower() for input_pattern in [
                                                    "enter your", "type your answer"
                                                ]):
                                                    all_question_parts.append((f"SUBPROBLEM {j+1} (IFRAME)", math_content))
                                                    

                                                    # Display each extracted subquestion
                                                    print(f"\nEXTRACTED SUBQUESTION {j+1} (IFRAME):")
                                                    print("=" * 60)
                                                    print("-" * 60)
                                                    print(math_content)
                                                    print("-" * 60)
                                                    continue
                            
                            # Use fallback text if needed
                            if sub_text and len(sub_text) > 5 and not any(input_pattern in sub_text.lower() for input_pattern in [
                                "enter your", "type your answer"
                            ]):
                                all_question_parts.append((f"SUBPROBLEM {j+1} (IFRAME)", sub_text))
                                

                                # Display each extracted subquestion
                                print(f"\nEXTRACTED SUBQUESTION {j+1} (IFRAME FALLBACK):")
                                print("=" * 60)
                                print("-" * 60)
                                print(sub_text)
                                print("-" * 60)
                        
                        driver.switch_to.default_content()
                    except WebDriverException as e_iframe_wd:
                        print(f"WebDriverException while processing an iframe: {e_iframe_wd}")
                        driver.switch_to.default_content() # Attempt to switch back
                        # This iframe might be problematic, continue to the next if any
                    except Exception as e_iframe:
                        print(f"Error processing an iframe: {e_iframe}")
                        try:
                            driver.switch_to.default_content() # Ensure we switch back
                        except WebDriverException:
                            print("Could not switch back from iframe, session might be lost.")
                            raise # Re-raise if we can't even switch back
                        continue
            except WebDriverException as e_wd:
                print(f"WebDriverException while finding/looping through iframes: {e_wd}")
                # If session is lost here, default_content might fail.
                try:
                    driver.switch_to.default_content()
                except WebDriverException:
                    print("Could not switch back from iframe after error, session might be lost.")
            except Exception as e:
                print(f"Error checking iframes: {e}")
                try:
                    driver.switch_to.default_content()
                except WebDriverException:
                     print("Could not switch back from iframe after error, session might be lost.")

        # Process and clean the extracted text
        if all_question_parts:
            # Format the combined question text
            combined_question = ""
            
            # First add the main problem
            for label, text in all_question_parts:
                if "MAIN PROBLEM" in label:
                    cleaned_text = clean_question_text(text)
                    if cleaned_text:
                        combined_question += cleaned_text + "\n\n"
                    break
            
            # Then add all subproblems
            subproblem_count = 0
            for label, text in all_question_parts:
                if "SUBPROBLEM" in label:
                    cleaned_text = clean_question_text(text)
                    if cleaned_text:
                        subproblem_count += 1
                        combined_question += f"{subproblem_count}) {cleaned_text}\n\n"
            
            # Remove trailing newlines
            combined_question = combined_question.strip()
            
            if combined_question:
                return [combined_question]
        
        # Fallback method if the specific classes are not found
        print("Could not find standard problem structure. Trying alternative extraction...")
        
        try:
            # Look for specific math-related selectors
            math_selectors = [
                ".statement-container", 
                "[data-test='question-text']",
                ".question-text",
                ".problem-text"
            ]
            
            for selector in math_selectors:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and elements[0].text.strip():
                    text = elements[0].text.strip()
                    cleaned_text = clean_question_text(text)
                    if cleaned_text:
                        print("\nFALLBACK EXTRACTION:")
                        print("===================")
                        print("-" * 60)
                        print(cleaned_text)
                        print("-" * 60)
                        return [cleaned_text]
        except WebDriverException as e_wd:
            print(f"WebDriverException during fallback extraction: {e_wd}")
        except Exception as e:
            print(f"Error in fallback extraction: {e}")

    except WebDriverException as e_main_extract:
        print(f"A WebDriverException occurred during question extraction: {e_main_extract}")
        print("This often means the browser session was lost or the page is not accessible.")
        return [] # Return empty list as session is likely invalid

    print("No valid questions found on page.")
    return []

def open_mathspace(credentials=None):
    """
    Opens mathspace.co using Selenium Chrome webdriver and logs in
    """
    print("Initializing Chrome webdriver...")

    # Set up Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")  # Start with maximized browser

    # --- YOU MUST PROVIDE THE PATH TO 'chromedriver.exe' ---
    # Download chromedriver.exe from: https://googlechromelabs.github.io/chrome-for-testing/
    # Example path (replace with your actual path):
    # chromedriver_path = r"C:\path\to\your\chromedriver.exe"
    chromedriver_path = r"c:\Users\ruann\.wdm\drivers\chromedriver\win64\136.0.7103.49\chromedriver-win32\chromedriver.exe" # <--- *** REPLACE THIS PATH IF NEEDED ***
    
    driver = None # Initialize driver to None

    # Check if the specified path exists
    if not os.path.exists(chromedriver_path):
        print(f"ERROR: ChromeDriver executable not found at the specified path: {chromedriver_path}")
        print("Please ensure the path is correct and points to 'chromedriver.exe'.")
        print("Attempting fallback using WebDriver Manager...")
        # Fallback to WebDriver Manager if the manual path is wrong
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception as e_fallback:
            print(f"Fallback with WebDriver Manager also failed: {e_fallback}")
            print("Please fix the chromedriver_path in the script or ensure WebDriver Manager can download the driver.")
            return None # Indicate failure
    else:
        print(f"Using ChromeDriver from: {chromedriver_path}")
        service = Service(executable_path=chromedriver_path)
        try:
            # Initialize the Chrome webdriver using the specified service
            driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception as e_manual:
            print(f"Error initializing WebDriver with specified path '{chromedriver_path}': {e_manual}")
            print("This might happen if the chromedriver version doesn't match your Chrome browser version.")
            print("Attempting fallback using WebDriver Manager...")
            # Fallback attempt if manual path fails (e.g., version mismatch)
            try:
                service_fallback = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service_fallback, options=chrome_options)
            except Exception as e_fallback:
                print(f"Fallback with WebDriver Manager also failed: {e_fallback}")
                return None # Indicate failure

    if driver is None:
        print("Failed to initialize WebDriver.")
        return None

    # Open Mathspace website
    print("Opening mathspace.co...")
    try:
        driver.get("https://mathspace.co/accounts/login/")
    except Exception as e:
        print(f"Error navigating to Mathspace login page: {e}")
        if driver:
            driver.quit()
        return None

    # Login to Mathspace
    try:
        login(driver, credentials)
    except Exception as e:
        print(f"Error during login process: {e}")
        if driver:
            driver.quit()
        return None

    print("Mathspace.co opened and logged in successfully")
    return driver

if __name__ == "__main__":
    driver = None
    active_problem_url = None  # Stores the URL of the problem page currently being processed

    try:
        driver = open_mathspace() 

        if driver is None:
            print("Failed to initialize WebDriver. Exiting.")
            exit()

        print("\nBrowser opened and logged in.")
        print("Monitoring navigation for problem pages (URL containing 'state=problem')...")
        print("Press Ctrl+C to exit.")

        while True:
            try:
                # Check for "Continue Practicing" button first
                try:
                    continue_practicing_button_selector = "[data-tracking-id='Work/EndScreen/ContinuePracticing']"
                    # Wait for a very short duration to see if the button is clickable
                    continue_button = WebDriverWait(driver, 1).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, continue_practicing_button_selector))
                    )
                    if continue_button: # Should always be true if WebDriverWait didn't timeout
                        print("\nFound 'Continue Practicing' button. Clicking it...")
                        # Scroll into view and click using JavaScript for robustness
                        driver.execute_script("arguments[0].scrollIntoView(true);", continue_button)
                        time.sleep(0.2) # Brief pause after scroll
                        driver.execute_script("arguments[0].click();", continue_button)
                        # continue_button.click() # Standard click as an alternative
                        print("'Continue Practicing' button clicked.")
                        time.sleep(1.5) # Give page time to load/transition
                        active_problem_url = None  # Reset active problem URL as page state has changed
                        continue # Restart the loop to re-evaluate the current URL and page state
                except TimeoutException:
                    # Button not found or not clickable within 1 sec, this is normal, so pass silently
                    pass
                except WebDriverException as e_continue_btn:
                    # Log if there's an issue interacting with the button if found
                    print(f"WebDriverException while trying to click 'Continue Practicing' button: {e_continue_btn}")
                except Exception as e_general_continue:
                    print(f"Unexpected error with 'Continue Practicing' button logic: {e_general_continue}")
                    traceback.print_exc()

                current_url = driver.current_url

                if "state=problem" in current_url:
                    if current_url != active_problem_url:
                        print(f"\nNew problem page detected: {current_url}")
                        active_problem_url = current_url
                        # Give the page a moment to load if we just navigated
                        time.sleep(2)  # Initial delay for new problem page
                    
                    # Periodically extract from the active problem page
                    print(f"\nChecking for questions on: {active_problem_url}")
                    
                    questions = extract_questions(driver) # This function already prints extraction details
                    
                    if questions and questions[0]:
                        cleaned_text = questions[0]
                        print("\n>>> Cleaned Extracted Question Text <<<")
                        print("===================================")
                        print(cleaned_text)
                        print("===================================")

                        # Attempt to calculate the extracted text
                        print("\n>>> Calculation Attempt <<<")
                        print("===================================")
                        calculation_result = calculate_expression(cleaned_text)
                        if isinstance(calculation_result, str) and "Error:" in calculation_result:
                            print(f"Could not calculate: {calculation_result}")
                        else:
                            print(f"The expression: {cleaned_text}")
                            print(f"Calculated Result: {calculation_result}")
                            print("===================================")

                            # Attempt to input the calculated answer into the textbox
                            try:
                                answer_value = str(calculation_result)
                                print(f"\nAttempting to input answer '{answer_value}' into text box...")
                                
                                # Selector for the MathQuill input field when it's initially empty
                                input_field_selector = ".mq-root-block.mq-empty"
                                
                                # Wait for the input field to be present and clickable (in its empty state)
                                answer_box = WebDriverWait(driver, 10).until(
                                    EC.element_to_be_clickable((By.CSS_SELECTOR, input_field_selector))
                                )
                                print(f"Found initial answer box (selector: '{input_field_selector}'). It should have 'mq-empty' class.")

                                # Attempt to click outside to ensure it's not focused by our detection,
                                # allowing the page's auto-select to trigger the class change.
                                try:
                                    print("Attempting to click body to deselect the input field...")
                                    body_element = driver.find_element(By.TAG_NAME, "body")
                                    ActionChains(driver).click(body_element).perform()
                                    time.sleep(0.3) # Short pause for deselection to register
                                    print("Clicked body. Input field should now be deselected.")
                                except Exception as e_deselect:
                                    print(f"Could not click body to deselect, proceeding anyway: {e_deselect}")
                                
                                # Now, wait for the page to auto-select the box,
                                # which we expect to remove the 'mq-empty' class.
                                print("Waiting for the page to auto-select the input box (expecting 'mq-empty' class to be removed by the page)...")
                                try:
                                    # Wait up to 7 seconds for 'mq-empty' class to disappear from the specific answer_box element
                                    WebDriverWait(driver, 7).until(
                                        lambda d: "mq-empty" not in answer_box.get_attribute("class").split()
                                    )
                                    print("Input box state changed (likely auto-selected by the page, 'mq-empty' removed).")
                                except TimeoutException:
                                    print("Timed out waiting for 'mq-empty' class to be removed by page auto-selection. The box might already be in the desired state, or auto-selection works differently/failed.")
                                except StaleElementReferenceException:
                                    print("Answer box became stale while waiting for class change. Re-finding might be needed if input fails.")
                                    # If it's stale, the original answer_box reference is no longer good.
                                    # For now, we'll let it try to proceed, but this indicates a potential issue.
                                except Exception as e_class_wait:
                                    print(f"Error while waiting for class change after attempting deselection: {e_class_wait}. Proceeding...")

                                # Using ActionChains for a more robust click and send_keys
                                actions = ActionChains(driver)
                                # Scroll the answer box into view before clicking
                                driver.execute_script("arguments[0].scrollIntoView(true);", answer_box)
                                time.sleep(0.2) # Brief pause after scroll
                                actions.click(answer_box) # Click to ensure focus, even if auto-selected
                                actions.pause(0.5) # Brief pause for field activation
                                actions.send_keys(answer_value) # Send keys to the (now focused) element
                                actions.perform()
                                
                                print(f"Successfully input: {answer_value} into the text box using ActionChains.")
                                print("===================================")

                            except TimeoutException:
                                print(f"Could not find or click the answer input box with selector: '{input_field_selector}' within 10 seconds.")
                                print("===================================")
                            except WebDriverException as e_input:
                                print(f"Error interacting with the answer input box: {e_input}")
                                print("===================================")
                            except Exception as e_general_input:
                                print(f"An unexpected error occurred while trying to input the answer: {e_general_input}")
                                traceback.print_exc()
                                print("===================================")
                        # The following print was part of the else block for calculation_result,
                        # it should be outside to correctly close the "Calculation Attempt" block.
                        # print("===================================") # This was moved up

                    else:
                        # extract_questions already prints "No valid questions found on page."
                        # or other diagnostic messages if extraction fails at various points.
                        print("No new question text to display from the last check, or page content might be loading/empty.")
                    
                    # Wait before the next check/extraction attempt on a problem page
                    print(f"Waiting for 2 seconds before next check on {active_problem_url}...")
                    time.sleep(2)

                else:  # Not on a "state=problem" page
                    if active_problem_url is not None:
                        print(f"\nNavigated away from problem page: {active_problem_url}")
                        active_problem_url = None  # Reset when navigating away
                    
                    # Check URL more frequently when not on a problem page
                    time.sleep(1)

            except WebDriverException as e_wd:
                print(f"\nWebDriverException in monitoring loop: {e_wd}")
                if "target window already closed" in str(e_wd).lower() or \
                   "no such window" in str(e_wd).lower() or \
                   "unable to connect to renderer" in str(e_wd).lower():
                    print("Browser window seems to be closed. Exiting script.")
                    break 
                else:
                    print("A WebDriver error occurred. Will attempt to continue monitoring after a short delay.")
                    time.sleep(5) # Wait a bit before retrying after a generic WebDriver error
            except Exception as e_loop:
                print(f"\nError in monitoring loop: {e_loop}")
                traceback.print_exc()
                print("Will attempt to continue monitoring after a short delay.")
                time.sleep(10) # Wait longer after an unexpected error

    except KeyboardInterrupt:
        print("\nScript interrupted by user (Ctrl+C).")
    except Exception as e_main:
        print(f"\nAn unhandled error occurred in the main script: {e_main}")
        traceback.print_exc()
    finally:
        if driver is not None:
            try:
                print("\nClosing browser...")
                driver.quit()
                print("Browser closed.")
            except Exception as e_quit:
                print(f"Error closing browser (it might have already been closed): {e_quit}")
        print("Script finished.")