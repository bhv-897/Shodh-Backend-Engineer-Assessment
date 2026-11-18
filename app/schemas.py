from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

class Input(BaseModel): model_config=ConfigDict(extra="forbid")
class Register(Input): name:str=Field(min_length=1,max_length=160); email:str=Field(max_length=320); password:str=Field(min_length=12,max_length=128)
class Login(Input): email:str; password:str
class OrgCreate(Input): name:str=Field(min_length=1,max_length=200)
class MemberAdd(Input): email:str; role:str
class RoleUpdate(Input): role:str
class ProblemCreate(Input): title:str
class VersionCreate(Input): statement:str; execution_limits:dict; runtime_configuration:dict
class SuiteCreate(Input): pass
class CaseCreate(Input): identifier:str; input_data:str; expected_output:str; is_hidden:bool=False; points:int=Field(default=0,ge=0)
class ContestCreate(Input): title:str; start_time:datetime; end_time:datetime; scoring_mode:str="icpc"; penalty_minutes_per_wrong:int=20
class ContestUpdate(Input): title:str|None=None; start_time:datetime|None=None; end_time:datetime|None=None; scoring_mode:str|None=None; penalty_minutes_per_wrong:int|None=None
class ContestProblemCreate(Input): problem_id:int; problem_version_id:int; test_suite_id:int; display_order:int; points:int=Field(ge=0)
class SubmissionCreate(Input): source_code:str; language:str
class VerdictCreate(Input): verdict:str; score:int=0; execution_time_ms:int|None=None; memory_used_kb:int|None=None; public_message:str|None=None; private_diagnostics:str|None=None
