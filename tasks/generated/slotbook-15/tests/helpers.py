from datetime import date

from slotbook.bookings import Calendar
from slotbook.resources import Directory, Room
from slotbook.timerange import TimeRange
from slotbook.zones import at

DAY = date(2026, 3, 2)


def utc(h, mi=0, d=2):
    return at("UTC", 2026, 3, d, h, mi)


def ist(h, mi=0, d=2):
    return at("IST", 2026, 3, d, h, mi)


def rng(h1, m1, h2, m2, d=2):
    return TimeRange(utc(h1, m1, d), utc(h2, m2, d))


def make_calendar():
    return Calendar(Directory([Room("Atlas", 4), Room("Borealis", 8), Room("Kochi", 6, zone="IST")]))
