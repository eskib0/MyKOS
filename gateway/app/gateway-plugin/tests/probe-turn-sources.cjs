const assert = require('node:assert/strict');
(async () => {
  const mod = await import('../mykos-ui/chat-loop.js');
  const tool = {role:'tool', content:JSON.stringify({ok:true, action:'web_search', results:[{title:'Old',url:'https://example.org/old'}]})};
  const messages = [tool, {role:'assistant',content:'old'}, {role:'user',content:'hello'}];
  assert.deepEqual(mod.sourceCardsFromMessages(messages, true), []);
  assert.equal(mod.sourceCardsFromMessages([...messages, tool, {role:'tool',content:'{}'}], true).length, 1);
  assert.equal(mod.sourceCardsFromMessages(messages).length, 1);
  const deps = {now:()=>'', model:{request:async()=>({message:{content:'hello'},done:true})}, worker:{catalog:async()=>({schemas:[],sensitive:[]}),activity:async()=>{},saveMessage:async(_,m)=>m},authority:{}};
  const result = await mod.runChatLoop({model:'qwen3:8b',messages,conversation_id:'isolated',generation:{}},deps);
  assert.deepEqual(result.sources, []);
  assert.equal(result.message.sources, undefined);
  console.log('5/5 turn source assertions passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
