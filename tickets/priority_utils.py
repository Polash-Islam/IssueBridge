from .models import TicketPriority


def move_priorities_to_temporary_ranks():
    priorities = list(TicketPriority.objects.order_by("pk"))
    used = {priority.rank for priority in priorities}
    candidate = 32767
    for priority in priorities:
        while candidate in used:
            candidate -= 1
        if candidate < 1:
            raise ValueError("There are too many ticket priorities to resequence safely.")
        used.remove(priority.rank)
        priority.rank = candidate
        priority.save(update_fields=["rank"])
        used.add(candidate)
        candidate -= 1
