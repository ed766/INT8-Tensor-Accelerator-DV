#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

struct Event { long cycle; std::string kind,tag,arg0,arg1,arg2; };
static std::vector<std::string> split(const std::string& line) {
  std::vector<std::string> out; std::stringstream stream(line); std::string field;
  while(std::getline(stream,field,',')) out.push_back(field);
  return out;
}
static long number(const std::string& value,int base=10){return std::stol(value,nullptr,base);}

int main(int argc,char**argv){
  if(argc!=6){std::cerr<<"usage: checker TRACE K BATCH FAULT PATTERN\n";return 2;}
  int k=std::stoi(argv[2]),batch=std::stoi(argv[3]),fault=std::stoi(argv[4]),pattern=std::stoi(argv[5]);
  std::ifstream input(argv[1]);std::string line;std::getline(input,line);std::vector<Event> events;
  while(std::getline(input,line)){auto f=split(line);if(f.size()>=6)events.push_back({number(f[0]),f[1],f[2],f[3],f[4],f[5]});}
  std::vector<std::string> failures;int checks=0;
  auto require=[&](bool ok,const char*name){checks++;if(!ok)failures.emplace_back(name);};
  auto count=[&](const std::string&kind){return std::count_if(events.begin(),events.end(),[&](const Event&e){return e.kind==kind;});};
  auto first=[&](const std::string&kind){return std::find_if(events.begin(),events.end(),[&](const Event&e){return e.kind==kind;});};
  require(count("submit")==1,"submit_count");require(count("completion")==1,"completion_count");
  auto submit=first("submit"),completion=first("completion");
  require(submit!=events.end()&&completion!=events.end()&&submit<completion,"completion_after_submit");
  require(count("apb_write")==8,"apb_write_count");
  if(completion!=events.end()){
    require(number(completion->tag)==0x35,"completion_tag");
    require(number(completion->arg0)==(fault?fault+1:0),"completion_status");
  }
  int commands=count("command"),chunks=count("chunk"),results=count("result");
  int reads=0,writes=0;for(const auto&e:events)if(e.kind=="memory")(e.arg0=="1"?writes:reads)++;
  if(fault==0){
    require(commands==batch,"command_per_vector");require(chunks==batch*(k/4),"chunk_count");
    require(results==batch,"result_count");require(reads==batch*(k/4),"read_count");require(writes==batch,"write_count");
    int expected_signed=pattern==0?k:pattern==1?0:pattern==2?std::min(127,10*(k/4)):pattern==3?-k:127;
    uint32_t byte=uint32_t(expected_signed)&0xffu;
    uint32_t expected=byte|(byte<<8)|(byte<<16)|(byte<<24);bool numerical=true;
    for(const auto&e:events)if(e.kind=="result"&&uint32_t(number(e.arg1,16))!=expected)numerical=false;
    require(numerical,"numerical_result");if(completion!=events.end())require(number(completion->arg1)==batch,"vectors_done");
    auto last_write=events.end();for(auto it=events.begin();it!=events.end();++it)if(it->kind=="memory"&&it->arg0=="1")last_write=it;
    require(last_write!=events.end()&&completion!=events.end()&&last_write<completion,"completion_after_output_write");
  }else if(fault==1||fault==3){
    require(commands==0,"no_command_after_input_fault");require(writes==0,"no_output_write_after_input_fault");
    if(completion!=events.end())require(number(completion->arg1)==0,"zero_vectors_done");
  }else{
    require(commands==1,"command_before_output_fault");require(chunks==k/4,"chunks_before_output_fault");
    require(results==1,"result_before_output_fault");if(completion!=events.end())require(number(completion->arg1)==0,"failed_vector_not_committed");
  }
  std::cout<<"MODEL_RESULT|status="<<(failures.empty()?"PASS":"FAIL")<<"|checks="<<checks<<"|first_mismatch="<<(failures.empty()?"none":failures.front())<<"\n";
  return failures.empty()?0:1;
}
