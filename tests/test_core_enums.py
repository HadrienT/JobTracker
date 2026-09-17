from enum import StrEnum

from jobtracker.core import enums


def test_every_enum_is_a_str_enum() -> None:
    enum_classes = [
        obj
        for name in dir(enums)
        if isinstance(obj := getattr(enums, name), type) and issubclass(obj, StrEnum)
    ]
    assert len(enum_classes) >= 7
    for enum_cls in enum_classes:
        assert issubclass(enum_cls, StrEnum)


def test_visa_status_has_three_states() -> None:
    assert {member.value for member in enums.VisaStatus} == {"sponsors", "no", "unknown"}
