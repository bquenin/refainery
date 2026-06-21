def truncate_string($limit):
  if . == null then null
  else
    tostring as $value
    | if ($value | length) > $limit then
        ($value[0:$limit] + "...<truncated>")
      else
        $value
      end
  end;

def truncate_value($limit):
  if . == null then null
  elif type == "string" then . | truncate_string($limit)
  else
    tojson as $json
    | if ($json | length) > $limit then
        {
          _truncated: true,
          preview: ($json[0:$limit] + "...<truncated>")
        }
      else
        .
      end
  end;

def message_preview($message; $limit):
  if $message == null then null
  else
    {
      index: $message.index,
      entry_index: $message.entry_index,
      block_index: $message.block_index,
      role: $message.role,
      timestamp: $message.timestamp,
      text: (($message.text // "") | truncate_string($limit))
    }
  end;

def previous_text($messages; $index; $role):
  ([
    $messages[]
    | select(.index < $index and .role == $role and ((.text // "") != ""))
  ] | last) as $message
  | message_preview($message; 700);

def next_text($messages; $index; $role):
  ([
    $messages[]
    | select(.index > $index and .role == $role and ((.text // "") != ""))
  ][0]) as $message
  | message_preview($message; 700);

def call_command($call):
  if $call == null then ""
  else
    # tool_input is usually an object, but some providers store it as a raw string; guard the type.
    (if (($call.tool_input | type) == "object") then ($call.tool_input.cmd // $call.tool_input.command) else null end) as $raw
    | if $raw == null then ""
      elif ($raw | type) == "array" then
        # shell wrapper like ["bash","-lc","<script>"]: use the script after a -c/-lc flag, else join
        ([$raw | to_entries[] | select((.value | type) == "string" and (.value | test("^-[A-Za-z]*c$"))) | .key] | last) as $ci
        | if ($ci != null) and ($raw[$ci + 1] != null) then ($raw[$ci + 1] | tostring)
          else ($raw | map(tostring) | join(" ")) end
      else ($raw | tostring) end
  end;

# A pipeline/chain stage that only reads/inspects content.
def inspection_segment:
  test("(?i)^(sed|cat|nl|rg|grep|find|ls|head|tail|less|more)\\b")
  or test("(?i)^git\\s+(show|diff|log|grep|status|cat-file)\\b")
  or test("(?i)^mnemonai\\s+(show|list)\\b")
  or test("(?i)^\\S*(evidence|triage)\\.sh\\b");

# Reads plus harmless glue (env assignments, builtins, text processors) that cannot themselves be the failing program.
def benign_segment:
  inspection_segment
  or test("(?i)^[A-Za-z_][A-Za-z0-9_]*=")
  or test("(?i)^(cd|echo|printf|export|pwd|true|false|set|:|sort|uniq|wc|cut|tr|column|awk|jq)\\b");

def inspection_like_call($call):
  if $call == null then false
  elif (($call.tool_name // "") | test("^(Read|ReadFile)$")) then true
  else
    # Treat as inspection only when EVERY stage is benign and at least one actually reads — so a chain/pipe into a
    # real program (e.g. `cat x | python y`, `ls && cargo build`) whose later stage failed is NOT suppressed.
    ([call_command($call) | splits("\\|\\||&&|;|\\||\\n") | gsub("^\\s+|\\s+$"; "") | select(. != "")]) as $segments
    | ($segments | length) > 0
      and ($segments | any(inspection_segment))
      and ($segments | all(benign_segment))
  end;

def recovery_signal($message):
  (($message.text // "") | test("(?i)(rerun|retry|try again|trying again|not supported|unsupported|isn.t supported|does not support|doesn.t support|permission denied|command not found|no such file|invalid option|parse error|quoting typo|bad jq|fixing|correcting|work ?around|abandon|gave up|give up|does not work|doesn.t work|that failed)"));

def classify_result:
  (.text // "") as $text
  | (($text | capture("(?m)^(?:Process exited with code|Exit code) (?<code>[0-9]+)$")? | .code | tonumber) // null) as $text_exit_code
  | (.tool_result_exit_code // $text_exit_code) as $normalized_exit_code
  | ((.tool_result_status // "") | tostring) as $status
  | (.tool_result_error == true) as $structured_error
  | ($status | test("(?i)^(error|errored|failed|failure|cancelled|canceled)$")) as $failing_status
  | ($normalized_exit_code != null and $normalized_exit_code != 0) as $nonzero_exit
  | ($text | test("(?im)(^|\\n)(traceback|error:|fatal:|panic:|exception:|permission denied|command not found|no such file|zsh:|bash:|sh:)")) as $runtime_signal
  | ($text | test("(?im)(^|\\n)(error\\[[A-Za-z0-9_-]+\\]:|compilation failed|could not compile)")) as $compiler_signal
  | ($text | test("(?i)(sandbox denied|failed in sandbox)")) as $sandbox_signal
  | ($text | test("(?m)^\\s*(ERROR|FATAL|PANIC)\\b")) as $log_error_signal
  | ($text | test("(?im)(^|\\n)\\s*usage:")) as $usage_signal
  | ($text | test("(?im)(illegal option|unknown option|unrecognized option|unrecognized argument|invalid option|invalid choice|invalid argument|no such option|missing required|too few arguments|unexpected argument)")) as $arg_failure_signal
  | ($text | test("(?m)^(?:[0-9]+\\t)?(diff --git|@@ |--- a/|\\+\\+\\+ b/)")) as $looks_like_diff
  | ($structured_error or $failing_status or $nonzero_exit) as $confirmed_failure
  | (
      $confirmed_failure == false
      and ($looks_like_diff == false)
      and (
        $runtime_signal
        or $compiler_signal
        or $sandbox_signal
        or $log_error_signal
        or ($usage_signal and $arg_failure_signal)
      )
    ) as $review_candidate
  | {
      signal: (if $confirmed_failure then "confirmed_failure" else "review_candidate" end),
      confidence: (if $confirmed_failure then "high" else "low" end),
      exit_code: $normalized_exit_code,
      reasons: [
        if $structured_error then "structured_error" else empty end,
        if $failing_status then "failing_status" else empty end,
        if $nonzero_exit then "nonzero_exit" else empty end,
        if $runtime_signal then "runtime_signal" else empty end,
        if $compiler_signal then "compiler_signal" else empty end,
        if $sandbox_signal then "sandbox_signal" else empty end,
        if $log_error_signal then "log_error_signal" else empty end,
        if ($usage_signal and $arg_failure_signal) then "argument_usage_signal" else empty end
      ],
      confirmed_failure: $confirmed_failure,
      review_candidate: $review_candidate,
      include: ($confirmed_failure or $review_candidate)
    };

. as $root
| .messages as $messages
| (
    $messages
    | map(select(.role == "tool_call" and (.tool_call_id // "") != ""))
    | map({key: .tool_call_id, value: .})
    # tool_call_id is unique per provider; on a (contract-violating) duplicate, from_entries keeps the last call
    | from_entries
  ) as $calls
| $messages[]
| select(.role == "tool_result")
| . as $result
| ($result | classify_result) as $classification
| (($result.tool_call_id // "") | if . == "" then null else ($calls[.] // null) end) as $call
| previous_text($messages; $result.index; "user") as $previous_user
| previous_text($messages; $result.index; "assistant") as $previous_assistant
| next_text($messages; $result.index; "assistant") as $next_assistant
# Benign non-failure states that exit nonzero / set an error marker but are not agent struggles:
# CI checks still pending or absent, and AskUserQuestion (a user interaction, including declines).
| (
    (($call.tool_name // "") == "AskUserQuestion")
    or (
      (call_command($call) | test("(?i)\\bgh\\s+pr\\s+checks\\b"))
      and (
        ($classification.exit_code == 8)
        or (($result.text // "") | test("(?i)no checks (reported|on|found)|no required checks"))
      )
    )
  ) as $benign_state
| (
    ($benign_state | not)
    and (
      $classification.confirmed_failure
      or (
        $classification.review_candidate
        and ((inspection_like_call($call) and (recovery_signal($next_assistant) | not)) | not)
      )
    )
  ) as $include
| select($include)
| {
    session: {
      provider: $root.conversation.provider,
      id: $root.conversation.id,
      path: $root.conversation.path,
      cwd: ($root.conversation.cwd // $root.conversation.project_path),
      timestamp: $root.conversation.timestamp,
      model: $root.conversation.model,
      parse_errors: ($root.conversation.parse_errors // [])
    },
    signal: $classification.signal,
    confidence: $classification.confidence,
    reasons: $classification.reasons,
    call: (
      if $call == null then null
      else {
        index: $call.index,
        entry_index: $call.entry_index,
        block_index: $call.block_index,
        timestamp: $call.timestamp,
        tool_call_id: $call.tool_call_id,
        tool_name: $call.tool_name,
        tool_input: ($call.tool_input | truncate_value(1600))
      }
      end
    ),
    result: {
      index: $result.index,
      entry_index: $result.entry_index,
      block_index: $result.block_index,
      timestamp: $result.timestamp,
      tool_call_id: $result.tool_call_id,
      exit_code: $classification.exit_code,
      tool_result_status: $result.tool_result_status,
      tool_result_error: $result.tool_result_error,
      text: (($result.text // "") | truncate_string(1600))
    },
    context: {
      previous_user: $previous_user,
      previous_assistant: $previous_assistant,
      next_assistant: $next_assistant
    },
    pairing: {
      has_call: ($call != null)
    }
  }
