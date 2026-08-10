from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional
import time
import uuid


# -----------------------------
# ENUMS
# -----------------------------

class Urgency(Enum):
    INTAKE_NON_URGENT = "INTAKE_NON_URGENT"   # פתיחת תיק - לא דחוף
    PERIOD_URGENT = "PERIOD_URGENT"           # המשך טיפול (וסת) - דחוף
    EXCEPTION_URGENT = "EXCEPTION_URGENT"     # אירוע חריג - דחוף


class ResourceType(Enum):
    SEC = "SECRETARY"
    DOC = "DOCTOR"
    US = "ULTRASOUND"
    NUR = "NURSE"
    LAB = "LAB"
    PSY = "PSYCHOLOGIST"


class PatientState(Enum):
    WAITING = "WAITING"
    ASSIGNED = "ASSIGNED"
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_FLOW = "OUT_OF_FLOW"


# -----------------------------
# CONSTANTS (HARD)
# -----------------------------

RESOURCE_CAPACITY = {
    ResourceType.SEC: 2,
    ResourceType.DOC: 3,
    ResourceType.US: 1,
    ResourceType.NUR: 4,
    ResourceType.LAB: 1,
    ResourceType.PSY: 1,
}

ASSIGNMENT_TIMEOUT_SECONDS = 180  # 3 minutes (not simulated with real sleep here)


# -----------------------------
# DATA MODELS
# -----------------------------

@dataclass
class Patient:
    full_name: str
    id_number: str
    urgency: Urgency
    has_all_pretests: Optional[bool] = None

    internal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: PatientState = PatientState.WAITING
    current_queue: Optional[ResourceType] = None
    queue_enter_time: float = field(default_factory=time.time)

    # After timeout, patient returns to head within same urgency
    head_of_queue_flag: bool = False
    head_flag_set_at: Optional[float] = None  # to clear after actual service starts
    
    # Track completed resources to avoid re-routing to same resource
    completed_resources: List[ResourceType] = field(default_factory=list)


@dataclass
class ResourceSlot:
    resource_type: ResourceType
    slot_id: int
    busy: bool = False
    assigned_patient_id: Optional[str] = None


# -----------------------------
# CORE SYSTEM
# -----------------------------

class IVFSystem:
    def __init__(self):
        self.resources: Dict[ResourceType, List[ResourceSlot]] = {
            r: [ResourceSlot(r, i + 1) for i in range(RESOURCE_CAPACITY[r])]
            for r in ResourceType
        }
        self.queues: Dict[ResourceType, List[Patient]] = {r: [] for r in ResourceType}
        self.patients: Dict[str, Patient] = {}

    # -------------------------
    # WORKFLOW: initial routing
    # -------------------------
    def add_patient(self, full_name: str, id_number: str, urgency: Urgency, has_all_pretests: Optional[bool]):
        p = Patient(full_name=full_name, id_number=id_number, urgency=urgency, has_all_pretests=has_all_pretests)

        # Rule: Intake without all pretests => OUT_OF_FLOW (needs to return later)
        if urgency == Urgency.INTAKE_NON_URGENT:
            if has_all_pretests is not True:
                p.state = PatientState.OUT_OF_FLOW
                self.patients[p.internal_id] = p
                return p

        # Otherwise they enter system at Secretary
        p.current_queue = ResourceType.SEC
        p.state = PatientState.WAITING
        p.queue_enter_time = time.time()
        self.queues[ResourceType.SEC].append(p)
        self.patients[p.internal_id] = p
        return p

    # -------------------------
    # WORKFLOW: routing patients to next resource
    # -------------------------
    def get_next_resource_for_patient(self, patient: Patient) -> Optional[ResourceType]:
        """Determine which resource the patient should go to next based on their urgency."""
        # Define the workflow sequence for each urgency level
        # All patients go through: SEC -> DOC -> possible additional resources
        
        workflow_sequence = {
            Urgency.INTAKE_NON_URGENT: [ResourceType.SEC, ResourceType.DOC, ResourceType.US, ResourceType.LAB],
            Urgency.PERIOD_URGENT: [ResourceType.SEC, ResourceType.DOC, ResourceType.NUR, ResourceType.LAB],
            Urgency.EXCEPTION_URGENT: [ResourceType.SEC, ResourceType.DOC, ResourceType.NUR, ResourceType.LAB],
        }
        
        sequence = workflow_sequence[patient.urgency]
        
        # Find the next resource in sequence that hasn't been completed yet
        for resource in sequence:
            if resource not in patient.completed_resources:
                return resource
        
        # If all resources completed, patient is done
        return None
    
    def route_patient_to_next_queue(self, patient: Patient) -> bool:
        """Move patient to the next queue in their workflow. Returns True if routed, False if done."""
        next_resource = self.get_next_resource_for_patient(patient)
        
        if next_resource is None:
            # Patient has completed all required resources
            patient.state = PatientState.OUT_OF_FLOW
            print(f"{patient.full_name} has completed all required services and exits the system.")
            return False
        
        # Move patient to the next queue
        patient.current_queue = next_resource
        patient.state = PatientState.WAITING
        patient.queue_enter_time = time.time()  # Reset waiting time for new queue
        patient.head_of_queue_flag = False
        patient.head_flag_set_at = None
        
        self.queues[next_resource].append(patient)
        print(f"{patient.full_name} routed to {next_resource.value} queue.\n")
        return True

    # -------------------------
    # DISPATCH: choose next for a resource type
    # -------------------------
    def dispatch_on_resource_freed(self, resource_type: ResourceType):
        """Run dispatch only when a resource becomes free. Assign to the first free slot."""
        slot = self._first_free_slot(resource_type)
        if slot is None:
            print(f"No FREE slots for {resource_type.value}.")
            return

        candidate = self._pick_next_candidate(resource_type)
        if candidate is None:
            print(f"No waiting patients in queue for {resource_type.value}.")
            return

        # Assign and lock decision
        slot.busy = True
        slot.assigned_patient_id = candidate.internal_id
        candidate.state = PatientState.ASSIGNED

        print(f"\nASSIGNED -> {resource_type.value} (slot {slot.slot_id})")
        print(f"Patient: {candidate.full_name} | ID: {candidate.id_number} | Urgency: {candidate.urgency.value}")

        print("\nDid the patient ENTER within 3 minutes?")
        print("Options: 1) yes  2) no (timeout -> next patient)")
        entered = input("Enter choice (1/2): ").strip()

        if entered == "1":
            # Patient starts service -> clear head flag and mark in service
            candidate.state = PatientState.IN_SERVICE
            candidate.head_of_queue_flag = False
            candidate.head_flag_set_at = None
            print(f"IN_SERVICE -> {candidate.full_name} started service on {resource_type.value}.\n")
            
            # After service completes, move patient to next queue or exit
            print(f"Has {candidate.full_name} completed service at {resource_type.value}?")
            print("Options: 1) yes  2) no (still in service)")
            service_completed = input("Enter choice (1/2): ").strip()
            
            if service_completed == "1":
                # Mark this resource as completed
                candidate.completed_resources.append(resource_type)
                slot.busy = False
                slot.assigned_patient_id = None
                
                # Route to next resource or exit
                self.route_patient_to_next_queue(candidate)
                
                print(f"Resource {resource_type.value} freed again -> dispatch will run now.\n")
                self.dispatch_on_resource_freed(resource_type)
        else:
            # Timeout -> patient returns to head within same urgency, and resource becomes free again
            candidate.state = PatientState.WAITING
            candidate.head_of_queue_flag = True
            candidate.head_flag_set_at = time.time()

            # IMPORTANT: do NOT reset queue_enter_time, because waiting time continues.
            # However, you can keep it as-is to preserve FIFO by original entry time.
            # Append back; the head_of_queue_flag ensures head within urgency.
            self.queues[resource_type].append(candidate)

            slot.busy = False
            slot.assigned_patient_id = None

            print(f"TIMEOUT -> {candidate.full_name} returned to HEAD within same urgency in {resource_type.value} queue.")
            print("Resource freed again -> dispatch will run now for the same resource.\n")
            self.dispatch_on_resource_freed(resource_type)

    def _first_free_slot(self, resource_type: ResourceType) -> Optional[ResourceSlot]:
        for s in self.resources[resource_type]:
            if not s.busy:
                return s
        return None

    def _pick_next_candidate(self, resource_type: ResourceType) -> Optional[Patient]:
        q = self.queues[resource_type]
        if not q:
            return None

        now = time.time()

        # Priority vector: (Urgent, HeadWithinUrgency, WaitingTime)
        # NOTE: head_of_queue_flag works only inside same urgency because urgency is first in tuple.
        def key(p: Patient):
            urgent = 1 if p.urgency != Urgency.INTAKE_NON_URGENT else 0
            head = 1 if p.head_of_queue_flag else 0
            waiting = now - p.queue_enter_time
            return (urgent, head, waiting)

        q.sort(key=key, reverse=True)
        chosen = q.pop(0)
        return chosen

    # -------------------------
    # DEBUG / DISPLAY
    # -------------------------
    def print_all_queues(self):
        print("\n================= QUEUES =================")
        for r in ResourceType:
            q = self.queues[r]
            if not q:
                continue
            print(f"\n{r.value}:")
            for p in q:
                urg = "URGENT" if p.urgency != Urgency.INTAKE_NON_URGENT else "NON_URGENT"
                print(f"- {p.full_name} | {p.id_number} | {p.urgency.value} ({urg}) | head={p.head_of_queue_flag}")
        print("==========================================\n")


# -----------------------------
# CLI INPUT HELPERS
# -----------------------------

def choose_urgency() -> Urgency:
    print("\nChoose URGENCY:")
    print("1) INTAKE_NON_URGENT  (פתיחת תיק - לא דחוף)")
    print("2) PERIOD_URGENT      (המשך טיפול / וסת - דחוף)")
    print("3) EXCEPTION_URGENT   (אירוע חריג - דחוף)")
    while True:
        c = input("Enter choice (1/2/3): ").strip()
        if c == "1":
            return Urgency.INTAKE_NON_URGENT
        if c == "2":
            return Urgency.PERIOD_URGENT
        if c == "3":
            return Urgency.EXCEPTION_URGENT
        print("Invalid choice. Try again.")


def choose_yes_no(prompt: str) -> bool:
    while True:
        val = input(f"{prompt} (y/n): ").strip().lower()
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("Invalid input. Use y/n.")


def main():
    system = IVFSystem()

    print("=== IVF Dispatch System (CLI) ===")
    print("Enter patients. When done, type 'done' for full name.\n")

    # Patient input loop
    while True:
        full_name = input("Full name (or 'done'): ").strip()
        if full_name.lower() == "done":
            break
        id_number = input("ID number: ").strip()

        urgency = choose_urgency()

        has_all_pretests = None
        if urgency == Urgency.INTAKE_NON_URGENT:
            has_all_pretests = choose_yes_no("Has ALL preliminary tests?")

        p = system.add_patient(full_name, id_number, urgency, has_all_pretests)
        if p.state == PatientState.OUT_OF_FLOW:
            print(f"Patient OUT_OF_FLOW (missing tests): {p.full_name}\n")
        else:
            print(f"Patient added to SECRETARY queue: {p.full_name}\n")

    # Show queues
    system.print_all_queues()

    # Dispatch loop (event-driven)
    print("Now simulate events: choose which RESOURCE became FREE.")
    print("Type 'exit' to stop.\n")

    resource_menu = {
        "1": ResourceType.SEC,
        "2": ResourceType.DOC,
        "3": ResourceType.US,
        "4": ResourceType.NUR,
        "5": ResourceType.LAB,
        "6": ResourceType.PSY,
    }

    while True:
        print("Resource freed menu:")
        print("1) SECRETARY   2) DOCTOR   3) ULTRASOUND   4) NURSE   5) LAB   6) PSYCHOLOGIST")
        choice = input("Select resource (1-6) or 'exit': ").strip().lower()
        if choice == "exit":
            break
        if choice not in resource_menu:
            print("Invalid selection.\n")
            continue

        system.dispatch_on_resource_freed(resource_menu[choice])
        system.print_all_queues()


if __name__ == "__main__":
    main()
