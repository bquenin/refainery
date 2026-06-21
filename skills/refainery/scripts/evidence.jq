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
| select($classification.include)
| (($result.tool_call_id // "") | if . == "" then null else ($calls[.] // null) end) as $call
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
      previous_user: previous_text($messages; $result.index; "user"),
      previous_assistant: previous_text($messages; $result.index; "assistant"),
      next_assistant: next_text($messages; $result.index; "assistant")
    },
    pairing: {
      has_call: ($call != null)
    }
  }
