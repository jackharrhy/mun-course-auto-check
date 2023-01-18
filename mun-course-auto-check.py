import shelve
import time
import sys
from typing import List, Optional
from pathlib import Path

from playwright.sync_api import sync_playwright, Page
from pydantic import BaseModel
import toml
import schedule
from twilio.rest import Client as TwilioClient


def get_course_url(term: int, subject: str, course_number: str) -> str:
    return f"https://selfservice.mun.ca/admit/bwskfcls.P_GetCrse?term_in={term}&sel_subj=dummy&sel_subj={subject}&SEL_CRSE={course_number}&SEL_TITLE=&BEGIN_HH=0&BEGIN_MI=0&BEGIN_AP=a&SEL_DAY=dummy&SEL_PTRM=dummy&END_HH=0&END_MI=0&END_AP=a&SEL_CAMP=dummy&SEL_SCHD=dummy&SEL_SESS=dummy&SEL_INSTR=dummy&SEL_INSTR=%25&SEL_ATTR=dummy&SEL_ATTR=%25&SEL_LEVL=dummy&SEL_LEVL=%25&SEL_INSM=dummy&sel_dunt_code=&sel_dunt_unit=&call_value_in=&rsts=dummy&crn=dummy&path=1&SUB_BTN=View%20Sections"


def get_login_url():
    return "https://login.mun.ca/cas/login?service=https%3A%2F%2Fselfservice.mun.ca%2Fadmit%2F"


class CourseDetails(BaseModel):
    capacity: int
    actual: int
    remaining: int


class Course(BaseModel):
    number: str
    subject: str
    crn: str
    details: Optional[CourseDetails]


class Config(BaseModel):
    class Notification(BaseModel):
        class Twilio(BaseModel):
            account_sid: str
            auth_token: str
            number_from: str
            number_to: str

        twilio: Optional[Twilio]

    username: str
    password: str
    term: str
    notification: Notification
    courses: List[Course]


config = Config(**toml.loads(Path("./config.toml").read_text()))

if config.notification.twilio is not None:
    twilio_config = config.notification.twilio
    twilio_client = TwilioClient(twilio_config.account_sid, twilio_config.auth_token)


def send_text(message: str):
    global twilio_client
    global config

    print("Sending text:", message)

    if twilio_client is None:
        print("Can't send text, no twilio_client")
        return

    twilio_config = config.notification.twilio

    twilio_client.messages.create(
        to=twilio_config.number_to, from_=twilio_config.number_from, body=message
    )

    print("Send message via Twilio")


def get_course_details(
    page: Page, course_url: str, crn: str
) -> Optional[CourseDetails]:
    page.goto(course_url)

    for elm in page.locator(
        "form table.datadisplaytable td:nth-child(2)"
    ).element_handles():
        if elm.text_content() == crn:
            parent = elm.get_property("parentElement").as_element()
            capacity = int(parent.query_selector("td:nth-child(12)").text_content())
            actual = int(parent.query_selector("td:nth-child(13)").text_content())
            remaining = int(parent.query_selector("td:nth-child(14)").text_content())

            return CourseDetails(capacity=capacity, actual=actual, remaining=remaining)


def course_details_different(cd1: CourseDetails, cd2: CourseDetails) -> bool:
    return not (cd1.dict() == cd2.dict())


def alert_course_details_different(
    course: Course, from_course_details: CourseDetails, to_course_details: CourseDetails
):
    text_message = f"Course Check: {course.subject} {course.number} ({course.crn}) updated: {from_course_details} -> {to_course_details}"
    send_text(text_message)
    print("Alerted")


def check():
    print("Checking...")

    global config

    with shelve.open("database") as db:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(get_login_url())

            page.locator('input[name="username"]').click()
            page.locator('input[name="username"]').fill(config.username)
            page.locator('input[name="password"]').click()
            page.locator('input[name="password"]').fill(config.password)
            page.locator('button:has-text("Log in")').click()
            page.wait_for_url("https://selfservice.mun.ca/admit/")

            for course in config.courses:
                course_id = (
                    f"{config.term}-{course.number}-{course.subject}-{course.crn}"
                )
                print(f"Checking {course.subject} {course.number} ({course.crn})...")
                course_details = get_course_details(
                    page,
                    get_course_url(config.term, course.subject, course.number),
                    course.crn,
                )
                course.details = course_details

                if db.get(course_id) is not None:
                    course_from_db: Course = db[course_id]
                    if course_details_different(course_details, course_from_db.details):
                        alert_course_details_different(
                            course, course_from_db.details, course_details
                        )
                    else:
                        print("Details the same, not alerting")

                db[course_id] = course
                print(f"Checked {course.subject} {course.number} ({course.crn})")

            browser.close()

    print("Finished checking")


def safe_check():
    try:
        check()
    except Exception as e:
        print(f"Exception: {e}", file=sys.stderr)


schedule.every(10).minutes.do(safe_check)

print("MUN Course Auto Check running")
print("Running for the first time...")
safe_check()
print("Scheduled to run every 10 minutes")

while True:
    schedule.run_pending()
    time.sleep(1)
