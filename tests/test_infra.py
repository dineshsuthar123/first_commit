from infra.manage import deploy_script, template


def test_deployment_contract():
    stack = template()
    resources = stack["Resources"]
    assert resources["Evidence"]["DeletionPolicy"] == "Retain"
    ingress = resources["SecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert [r["FromPort"] for r in ingress] == [80]
    bootstrap = resources["Runner"]["Properties"]["UserData"]["Fn::Base64"]
    assert "sha256sum -c" in bootstrap and "limit_except GET" in bootstrap
    script = deploy_script("example-bucket", "sources/abc.tar.gz", "a" * 64, "ap-south-1")
    assert "STATEPROOF_READ_ONLY=1" in script
    assert "--s3" in script and "--compare stable_key" in script
    assert "AWS_ACCESS_KEY_ID" not in script
