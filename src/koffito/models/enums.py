import enum


class Gender(enum.StrEnum):
    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class EventStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    REVEALED = "revealed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ParticipantStatus(enum.StrEnum):
    REGISTERED = "registered"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    ATTENDED = "attended"
    NO_SHOW = "no_show"


class ReportStatus(enum.StrEnum):
    OPEN = "open"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
